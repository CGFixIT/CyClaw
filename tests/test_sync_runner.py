"""Self-contained unit tests for sync.runner (no network, no real rclone).

Runnable with ``pytest --noconftest tests/test_sync_runner.py`` -- these tests do
NOT depend on tests/conftest.py fixtures (which import chromadb). The rclone
subprocess boundary is mocked via ``sync.runner.subprocess.run`` and the binary
resolution via ``sync.runner.shutil.which``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sync.config import RcloneConfig
from sync.runner import (
    MIN_RCLONE_MAJOR,
    MIN_RCLONE_MINOR,
    MIN_RCLONE_PATCH,
    FileEvent,
    SyncResult,
    build_bisync_argv,
    build_pull_argv,
    check_rclone_version,
    hash_changed_files,
    parse_log,
    reindex_exit_code_for,
    run_sync,
)
from utils.errors import RcloneNotInstalledError, RcloneVersionError
from utils.logger import reset_config_cache

FAKE_RCLONE = "/usr/bin/rclone"


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_config_cache()
    yield
    reset_config_cache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(tmp_path: Path, **overrides) -> RcloneConfig:
    """Build an RcloneConfig pointed entirely at tmp_path (no repo writes)."""
    corpus = Path(__file__).resolve().parent.parent / "data" / "corpus"
    kwargs: dict = {
        "local_path": str(corpus),
        "filter_file": str(tmp_path / "filters.txt"),
        "log_dir": str(tmp_path / "logs"),
        "workdir": str(tmp_path / "workdir"),
    }
    kwargs.update(overrides)
    return RcloneConfig(**kwargs)


def _version_mock(version: str) -> MagicMock:
    return MagicMock(returncode=0, stdout=f"rclone v{version}\n", stderr="")


# ---------------------------------------------------------------------------
# Version gate
# ---------------------------------------------------------------------------

def test_min_version_floor_is_1_68_2():
    assert (MIN_RCLONE_MAJOR, MIN_RCLONE_MINOR, MIN_RCLONE_PATCH) == (1, 68, 2)


def test_version_ok():
    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", return_value=_version_mock("1.68.2")):
        assert check_rclone_version() == (1, 68, 2)


def test_version_newer_ok():
    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", return_value=_version_mock("1.72.1")):
        assert check_rclone_version() == (1, 72, 1)


def test_version_too_old_raises():
    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", return_value=_version_mock("1.68.1")):
        with pytest.raises(RcloneVersionError):
            check_rclone_version()


def test_version_old_minor_raises():
    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", return_value=_version_mock("1.65.0")):
        with pytest.raises(RcloneVersionError):
            check_rclone_version()


def test_missing_binary_raises():
    with patch("sync.runner.shutil.which", return_value=None):
        with pytest.raises(RcloneNotInstalledError):
            check_rclone_version()


def test_unparseable_version_raises():
    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", return_value=MagicMock(returncode=0, stdout="garbage", stderr="")):
        with pytest.raises(RcloneVersionError):
            check_rclone_version()


# ---------------------------------------------------------------------------
# argv builders -- always a list, no shell, absolute binary
# ---------------------------------------------------------------------------

def test_pull_argv_is_list_no_shell(tmp_path):
    cfg = _make_cfg(tmp_path)
    argv = build_pull_argv(cfg, dry_run=False, log_path="/tmp/x.log", rclone_bin=FAKE_RCLONE)
    assert isinstance(argv, list)
    assert "shell" not in argv
    assert all(isinstance(a, str) for a in argv)
    assert argv[0] == FAKE_RCLONE
    assert Path(argv[0]).is_absolute()
    assert argv[1] == "copy"
    assert cfg.remote in argv
    assert cfg.local_path in argv
    assert "--filter-from" in argv
    assert cfg.filter_file in argv
    # rclone copy never deletes, so --max-delete is bisync-only (not in pull argv)
    assert f"--max-delete={cfg.max_delete}" not in argv
    assert f"--max-transfer={cfg.max_transfer}" in argv
    assert "--check-first" in argv
    assert "--log-file" in argv
    assert "--log-level" in argv


def test_pull_argv_dry_run_flag(tmp_path):
    cfg = _make_cfg(tmp_path)
    argv = build_pull_argv(cfg, dry_run=True, log_path="/tmp/x.log", rclone_bin=FAKE_RCLONE)
    assert "--dry-run" in argv


def test_checksum_toggles_with_cfg(tmp_path):
    cfg_on = _make_cfg(tmp_path, checksum=True)
    cfg_off = _make_cfg(tmp_path, checksum=False)
    assert "--checksum" in build_pull_argv(cfg_on, False, "/tmp/x.log", FAKE_RCLONE)
    assert "--checksum" not in build_pull_argv(cfg_off, False, "/tmp/x.log", FAKE_RCLONE)


def test_bisync_argv_is_list_with_conflict_flags(tmp_path):
    cfg = _make_cfg(tmp_path, direction="bisync")
    argv = build_bisync_argv(cfg, dry_run=False, log_path="/tmp/x.log", resync=True, rclone_bin=FAKE_RCLONE)
    assert isinstance(argv, list)
    assert argv[1] == "bisync"
    assert f"--conflict-resolve={cfg.conflict_resolve}" in argv
    assert f"--conflict-loser={cfg.conflict_loser}" in argv
    assert "--workdir" in argv
    assert cfg.workdir in argv
    assert "--resync" in argv
    # --max-delete is bisync-only (rclone copy never deletes)
    assert f"--max-delete={cfg.max_delete}" in argv


# ---------------------------------------------------------------------------
# Log parsing + hashing
# ---------------------------------------------------------------------------

def _write_log(tmp_path: Path) -> str:
    log = tmp_path / "rclone.log"
    log.write_text(textwrap.dedent("""\
        2026/06/20 02:10:01 INFO  : data/corpus/new.md: Copied (new)
        2026/06/20 02:10:02 INFO  : data/corpus/changed.md: Copied (replaced existing)
        2026/06/20 02:10:03 INFO  : data/corpus/gone.md: Deleted
        2026/06/20 02:10:04 ERROR : something went wrong on the wire
        2026/06/20 02:10:05 INFO  : unrelated noise line that should be ignored
    """), encoding="utf-8")
    return str(log)


def test_parse_log_events_and_errors(tmp_path):
    events, errors = parse_log(_write_log(tmp_path))
    kinds = {e.kind for e in events}
    assert kinds == {"added", "modified", "deleted"}
    assert any("something went wrong" in e for e in errors)


def test_parse_log_missing_file_tolerant(tmp_path):
    events, errors = parse_log(str(tmp_path / "nope.log"))
    assert events == []
    assert errors == []


def test_hash_changed_files_streams_and_skips_deleted(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("hello", encoding="utf-8")
    events = [
        FileEvent(kind="added", path="a.md"),
        FileEvent(kind="deleted", path="b.md"),
        FileEvent(kind="modified", path="missing.md"),
    ]
    out = hash_changed_files(events, str(tmp_path))
    by_path = {e.path: e for e in out}
    assert by_path["a.md"].sha256 is not None and len(by_path["a.md"].sha256) == 64
    assert by_path["b.md"].sha256 is None  # deleted -> never hashed
    assert by_path["missing.md"].sha256 is None  # not on disk -> None


# ---------------------------------------------------------------------------
# Audit dicts -- "file" key, never "query", no secret fields
# ---------------------------------------------------------------------------

def test_file_event_audit_uses_file_key_not_query():
    ev = FileEvent(kind="added", path="data/corpus/x.md", sha256="abc")
    d = ev.to_audit_dict(base="/repo/data/corpus")
    assert d["event"] == "sync_file_added"
    assert "file" in d
    assert "query" not in d
    assert d["file"] == "data/corpus/x.md"


def test_sync_result_audit_dict_no_secret_fields():
    res = SyncResult(
        success=True, direction="pull", started_at=1.0, finished_at=2.0,
        rclone_exit_code=0, corpus_changed=True,
    )
    d = res.to_audit_dict()
    assert "query" not in d
    keys = set(d.keys())
    assert not (keys & {"token", "refresh_token", "secret", "password", "stderr"})
    assert d["event"] == "sync_completed"


# ---------------------------------------------------------------------------
# run_sync end-to-end (mocked subprocess) + corpus_changed / exit-code wiring
# ---------------------------------------------------------------------------

def _patch_audit():
    return patch("sync.runner.audit_log")


def test_run_sync_corpus_changed_and_exit_10(tmp_path):
    cfg = _make_cfg(tmp_path)
    log_path = cfg.log_path

    def dispatch(argv, **kwargs):
        # argv must always be a list, never shell=True, binary absolute.
        assert isinstance(argv, list)
        assert kwargs.get("shell") is not True
        assert Path(argv[0]).is_absolute()
        if argv[1] == "version":
            return _version_mock("1.70.0")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(
            "2026/06/20 02:10:01 INFO  : data/corpus/new.md: Copied (new)\n",
            encoding="utf-8",
        )
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         _patch_audit():
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert result.success is True
    assert result.corpus_changed is True
    assert reindex_exit_code_for(result, cfg) == cfg.REINDEX_EXIT_CODE == 10


def test_run_sync_no_change_exit_0(tmp_path):
    cfg = _make_cfg(tmp_path)
    log_path = cfg.log_path

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("2026/06/20 02:10:01 INFO  : nothing to do\n", encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         _patch_audit():
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert result.success is True
    assert result.corpus_changed is False
    assert reindex_exit_code_for(result, cfg) == 0


def test_run_sync_safety_abort_exit_1(tmp_path):
    cfg = _make_cfg(tmp_path)
    log_path = cfg.log_path

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("", encoding="utf-8")
        return MagicMock(returncode=9, stdout="", stderr="Fatal error: max-delete threshold exceeded")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         _patch_audit():
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert result.success is False
    assert result.aborted_for_safety is True
    assert reindex_exit_code_for(result, cfg) == 1


def test_run_sync_other_failure_exit_2(tmp_path):
    cfg = _make_cfg(tmp_path)
    log_path = cfg.log_path

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("", encoding="utf-8")
        return MagicMock(returncode=1, stdout="", stderr="generic failure")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         _patch_audit():
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert result.success is False
    assert result.aborted_for_safety is False
    assert reindex_exit_code_for(result, cfg) == 2


def test_run_sync_audit_events_have_file_key_no_query(tmp_path):
    cfg = _make_cfg(tmp_path)
    log_path = cfg.log_path
    captured: list[dict] = []

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(
            "2026/06/20 02:10:01 INFO  : data/corpus/new.md: Copied (new)\n",
            encoding="utf-8",
        )
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         patch("sync.runner.audit_log", side_effect=lambda e: captured.append(e)):
        run_sync(cfg, rclone_bin=FAKE_RCLONE)

    file_events = [e for e in captured if e.get("event", "").startswith("sync_file_")]
    assert file_events, "expected at least one per-file audit event"
    for e in file_events:
        assert "file" in e
        assert "query" not in e
    # No secret-looking fields anywhere.
    for e in captured:
        assert not (set(e.keys()) & {"token", "refresh_token", "secret", "password", "stderr"})
