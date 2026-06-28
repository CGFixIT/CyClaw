"""Self-contained unit tests for sync.runner (no network, no real rclone).

Runnable with ``pytest --noconftest tests/test_sync_runner.py`` -- these tests do
NOT depend on tests/conftest.py fixtures (which import chromadb). The rclone
subprocess boundary is mocked via ``sync.runner.subprocess.run`` and the binary
resolution via ``sync.runner.shutil.which``.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sync.config import RcloneConfig
from sync.runner import (
    MIN_RCLONE_MAJOR,
    MIN_RCLONE_MINOR,
    MIN_RCLONE_PATCH,
    CheckResult,
    FileEvent,
    SyncResult,
    build_bisync_argv,
    build_check_argv,
    build_pull_argv,
    check_rclone_version,
    hash_changed_files,
    parse_log,
    reindex_exit_code_for,
    run_post_sync_check,
    run_sync,
)
from utils.errors import RcloneNotInstalledError, RcloneTimeoutError, RcloneVersionError, SyncRuntimeError
from utils.logger import reset_config_cache

# shutil.which returns a drive-letter absolute path on Windows; POSIX path on Linux.
FAKE_RCLONE = r"C:\Windows\rclone.exe" if sys.platform == "win32" else "/usr/bin/rclone"


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


def test_version_timeout_raises_rclone_timeout_error():
    # rclone is on PATH (which succeeds) but the version check subprocess stalls.
    # Must raise RcloneTimeoutError — NOT RcloneNotInstalledError — so callers
    # report the right diagnosis ("binary stalled") rather than "not installed".
    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[FAKE_RCLONE, "version"], timeout=10)):
        with pytest.raises(RcloneTimeoutError) as exc_info:
            check_rclone_version()
        assert exc_info.value.code == "RCLONE_TIMEOUT"
        assert "timed out" in exc_info.value.message


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


def test_fast_list_and_bwlimit_flags_toggle_with_cfg(tmp_path):
    cfg_off = _make_cfg(tmp_path)
    argv_off = build_pull_argv(cfg_off, False, "/tmp/x.log", FAKE_RCLONE)
    assert "--fast-list" not in argv_off
    assert not any(a.startswith("--bwlimit") for a in argv_off)

    cfg_on = _make_cfg(tmp_path, fast_list=True, bwlimit="8M")
    argv_on = build_pull_argv(cfg_on, False, "/tmp/x.log", FAKE_RCLONE)
    assert "--fast-list" in argv_on
    assert "--bwlimit=8M" in argv_on  # single clean token, never split


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
        # rclone logs paths relative to the transfer root (data/corpus), e.g.
        # "notes.md" -- NOT "data/corpus/notes.md". corpus_changed must still
        # fire on this realistic shape.
        Path(log_path).write_text(
            "2026/06/20 02:10:01 INFO  : notes.md: Copied (new)\n",
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


def test_run_sync_timeout_maps_to_sync_runtime_error(tmp_path):
    # A hung rclone (TimeoutExpired) must surface as a typed SyncRuntimeError
    # carrying the limit that tripped — and must NOT leak the remote spec/argv.
    cfg = _make_cfg(tmp_path, sync_timeout_sec=1)
    seen_timeout = {}

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        # Confirm the wall-clock ceiling is actually wired to the sync call.
        seen_timeout["value"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout"))

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         _patch_audit():
        with pytest.raises(SyncRuntimeError) as exc:
            run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert seen_timeout["value"] == 1  # the config ceiling reached subprocess.run
    assert exc.value.details.get("timeout_sec") == 1
    # The remote spec must never leak into the error message.
    assert "dropbox" not in str(exc.value).lower()


def test_run_sync_timeout_zero_passes_none_to_subprocess(tmp_path):
    # sync_timeout_sec=0 is the "unbounded" escape hatch -> timeout=None.
    cfg = _make_cfg(tmp_path, sync_timeout_sec=0)
    log_path = cfg.log_path
    seen_timeout = {}

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        seen_timeout["value"] = kwargs.get("timeout", "MISSING")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("", encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         _patch_audit():
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert result.success is True
    assert seen_timeout["value"] is None  # 0 -> unbounded


def test_run_sync_corpus_changed_ignores_rclone_internal_artifacts(tmp_path):
    # An rclone scratch/state file leaking into the log must NOT trip
    # corpus_changed (it is not corpus content).
    cfg = _make_cfg(tmp_path)
    log_path = cfg.log_path

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(
            "2026/06/20 02:10:01 INFO  : RCLONE_TEST: Copied (new)\n",
            encoding="utf-8",
        )
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         _patch_audit():
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert result.success is True
    assert result.corpus_changed is False


def test_run_sync_corpus_changed_ignores_nested_rclone_internal_artifacts(tmp_path):
    # rclone occasionally logs scratch/state files in a nested path
    # ("sub/.rclone-cache/state"). A root-only startswith() check would miss it
    # and wrongly trip corpus_changed -> a needless reindex. The per-component
    # check must treat a nested artifact as internal too.
    cfg = _make_cfg(tmp_path)
    log_path = cfg.log_path

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(
            "2026/06/20 02:10:01 INFO  : sub/.rclone-cache/state: Copied (new)\n",
            encoding="utf-8",
        )
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         _patch_audit():
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert result.success is True
    assert result.corpus_changed is False


def test_run_sync_corpus_changed_fires_on_nested_corpus_file(tmp_path):
    # A genuine corpus file in a subdirectory ("sub/notes.md") is NOT an rclone
    # artifact and MUST still trip corpus_changed.
    cfg = _make_cfg(tmp_path)
    log_path = cfg.log_path

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(
            "2026/06/20 02:10:01 INFO  : sub/notes.md: Copied (new)\n",
            encoding="utf-8",
        )
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         _patch_audit():
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert result.success is True
    assert result.corpus_changed is True


def test_run_sync_single_instance_lock_blocks_concurrent_run(tmp_path):
    # A pre-existing (fresh) lock directory means another run holds the lock;
    # run_sync must refuse rather than race a second rclone invocation.
    cfg = _make_cfg(tmp_path)
    lock_dir = Path(cfg.log_dir) / "sync.lock.d"
    lock_dir.mkdir(parents=True)

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        raise AssertionError("rclone must not run while the lock is held")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         _patch_audit():
        with pytest.raises(SyncRuntimeError):
            run_sync(cfg, rclone_bin=FAKE_RCLONE)


def test_run_sync_releases_lock_after_run(tmp_path):
    # After a normal run the lock directory must be gone so the next run can
    # acquire it.
    cfg = _make_cfg(tmp_path)
    log_path = cfg.log_path

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("INFO  : nothing to do\n", encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         _patch_audit():
        run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert not (Path(cfg.log_dir) / "sync.lock.d").exists()


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


def test_run_sync_raises_when_log_cannot_be_cleared(tmp_path):
    # rclone opens --log-file in append mode, so a previous run's log must be
    # cleared before this run or its FileEvents/ERROR lines would be replayed
    # (a false reindex signal or a phantom safety-abort). Plant a directory where
    # the log file belongs so the clear (open "w") raises IsADirectoryError -- the
    # fix must surface that as SyncRuntimeError, never silently parse stale data.
    cfg = _make_cfg(tmp_path)
    Path(cfg.log_path).mkdir(parents=True, exist_ok=True)

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", return_value=_version_mock("1.70.0")), \
         _patch_audit():
        with pytest.raises(SyncRuntimeError):
            run_sync(cfg, rclone_bin=FAKE_RCLONE)


def test_run_sync_clears_stale_log_before_run(tmp_path):
    # A stale log left from a prior run must NOT leak into this run's result.
    # Pre-seed the log with a deleted-file line + an ERROR; the mocked rclone run
    # writes only a single "Copied (new)" line. After the fix the result reflects
    # ONLY the fresh line -- the stale delete/error are gone.
    cfg = _make_cfg(tmp_path)
    log_path = cfg.log_path
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    Path(log_path).write_text(
        "2026/06/19 01:00:00 INFO  : stale.md: Deleted\n"
        "2026/06/19 01:00:00 ERROR : stale failure from a previous run\n",
        encoding="utf-8",
    )

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        # rclone appends to log_path; the fix truncated it first, so only this
        # fresh line is present when parse_log runs.
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("2026/06/20 02:10:01 INFO  : fresh.md: Copied (new)\n")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch):
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    kinds = {(ev.kind, ev.path) for ev in result.events}
    assert ("added", "fresh.md") in kinds
    assert ("deleted", "stale.md") not in kinds  # stale event was cleared
    assert result.errors == []  # stale ERROR line was cleared, not replayed


def test_run_sync_retries_on_transient_then_succeeds(tmp_path):
    # rclone exit 5 is "Temporary error (retry might fix it)". With sync_retries>0
    # the run must retry and a later success wins. Backoff 0 keeps the test instant.
    cfg = _make_cfg(tmp_path, sync_retries=2, retry_backoff_sec=0)
    log_path = cfg.log_path
    calls = {"sync": 0}
    captured: list[dict] = []

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        calls["sync"] += 1
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        if calls["sync"] < 2:
            # First attempt: transient failure, empty log, exit 5.
            Path(log_path).write_text("", encoding="utf-8")
            return MagicMock(returncode=5, stdout="", stderr="temporary error")
        # Second attempt: success with a real corpus change.
        Path(log_path).write_text(
            "2026/06/20 02:10:01 INFO  : notes.md: Copied (new)\n", encoding="utf-8"
        )
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         patch("sync.runner.audit_log", side_effect=lambda e: captured.append(e)):
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert calls["sync"] == 2  # one failed attempt + one success
    assert result.success is True
    assert result.corpus_changed is True  # the success attempt's log is what parsed
    assert result.errors == []  # the failed attempt's log was truncated, not replayed
    assert any(e.get("event") == "sync_retry" for e in captured)


def test_run_sync_no_retry_when_disabled(tmp_path):
    # Default sync_retries=0 -> a transient exit 5 is NOT retried (single shot).
    cfg = _make_cfg(tmp_path)
    log_path = cfg.log_path
    calls = {"sync": 0}

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        calls["sync"] += 1
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("", encoding="utf-8")
        return MagicMock(returncode=5, stdout="", stderr="temporary error")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         _patch_audit():
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert calls["sync"] == 1
    assert result.success is False
    assert reindex_exit_code_for(result, cfg) == 2  # non-safety failure


def test_run_sync_does_not_retry_nontransient_failure(tmp_path):
    # exit 1 (usage error) is deterministic, NOT transient: even with retries
    # configured it must run exactly once -- looping would never help.
    cfg = _make_cfg(tmp_path, sync_retries=3, retry_backoff_sec=0)
    log_path = cfg.log_path
    calls = {"sync": 0}

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        calls["sync"] += 1
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("", encoding="utf-8")
        return MagicMock(returncode=1, stdout="", stderr="generic failure")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch), \
         _patch_audit():
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert calls["sync"] == 1
    assert result.success is False


def test_run_sync_audit_events_have_file_key_no_query(tmp_path):
    cfg = _make_cfg(tmp_path)
    log_path = cfg.log_path
    captured: list[dict] = []

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(
            "2026/06/20 02:10:01 INFO  : notes.md: Copied (new)\n",
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


# ---------------------------------------------------------------------------
# Post-sync rclone check
# ---------------------------------------------------------------------------

def test_build_check_argv_is_list_with_remote_local_filter(tmp_path):
    cfg = _make_cfg(tmp_path)
    argv = build_check_argv(cfg, rclone_bin=FAKE_RCLONE)
    assert isinstance(argv, list)
    assert argv[1] == "check"
    assert cfg.remote in argv
    assert cfg.local_path in argv
    assert "--filter-from" in argv
    assert cfg.filter_file in argv
    # check is read-only: no --dry-run, no log-file writes.
    assert "--log-file" not in argv


def test_build_check_argv_includes_checksum_flag(tmp_path):
    cfg = _make_cfg(tmp_path, checksum=True)
    assert "--checksum" in build_check_argv(cfg, rclone_bin=FAKE_RCLONE)


def test_build_check_argv_omits_checksum_when_off(tmp_path):
    cfg = _make_cfg(tmp_path, checksum=False)
    assert "--checksum" not in build_check_argv(cfg, rclone_bin=FAKE_RCLONE)


def test_run_post_sync_check_ok_when_zero_differences(tmp_path):
    cfg = _make_cfg(tmp_path)
    ok_output = (
        "2026/06/20 00:00:00 INFO  : 0 differences found\n"
        "2026/06/20 00:00:00 INFO  : Found 0 missing on Local\n"
        "2026/06/20 00:00:00 INFO  : Found 0 missing on Remote\n"
    )
    with patch("sync.runner.subprocess.run",
               return_value=MagicMock(returncode=0, stdout="", stderr=ok_output)), \
         _patch_audit():
        cr = run_post_sync_check(cfg, rclone_bin=FAKE_RCLONE)
    assert cr.ok is True
    assert cr.differences == 0
    assert cr.missing_local == 0
    assert cr.missing_remote == 0
    assert cr.errors == []


def test_run_post_sync_check_not_ok_when_differences_found(tmp_path):
    cfg = _make_cfg(tmp_path)
    diff_output = (
        "2026/06/20 00:00:00 NOTICE: notes.md: sizes differ\n"
        "2026/06/20 00:00:00 INFO  : Found 1 missing on Local\n"
        "2026/06/20 00:00:00 INFO  : Found 0 missing on Remote\n"
        "2026/06/20 00:00:00 INFO  : 1 differences found\n"
    )
    with patch("sync.runner.subprocess.run",
               return_value=MagicMock(returncode=1, stdout="", stderr=diff_output)), \
         _patch_audit():
        cr = run_post_sync_check(cfg, rclone_bin=FAKE_RCLONE)
    assert cr.ok is False
    assert cr.differences == 1
    assert cr.missing_local == 1
    assert cr.missing_remote == 0
    assert len(cr.errors) == 1
    assert "notes.md" in cr.errors[0]


def test_run_post_sync_check_timeout_raises_sync_runtime_error(tmp_path):
    cfg = _make_cfg(tmp_path, sync_timeout_sec=1)
    with patch("sync.runner.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd=["rclone"], timeout=1)):
        with pytest.raises(SyncRuntimeError) as exc:
            run_post_sync_check(cfg, rclone_bin=FAKE_RCLONE)
    assert exc.value.details.get("op") == "check"


def test_run_sync_calls_check_on_success_when_configured(tmp_path):
    cfg = _make_cfg(tmp_path, post_sync_check=True)
    log_path = cfg.log_path

    check_output = (
        "2026/06/20 00:00:00 INFO  : 0 differences found\n"
        "2026/06/20 00:00:00 INFO  : Found 0 missing on Local\n"
        "2026/06/20 00:00:00 INFO  : Found 0 missing on Remote\n"
    )

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        if argv[1] == "check":
            return MagicMock(returncode=0, stdout="", stderr=check_output)
        # sync call
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("", encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch) as mrun, \
         _patch_audit():
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert result.check_result is not None
    assert result.check_result.ok is True
    # subprocess.run should have been called 3 times: version + sync + check.
    assert mrun.call_count == 3
    check_calls = [c for c in mrun.call_args_list if c.args[0][1] == "check"]
    assert len(check_calls) == 1


def test_run_sync_skips_check_on_dry_run(tmp_path):
    cfg = _make_cfg(tmp_path, post_sync_check=True)
    log_path = cfg.log_path

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("", encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch) as mrun, \
         _patch_audit():
        result = run_sync(cfg, dry_run=True, rclone_bin=FAKE_RCLONE)

    assert result.check_result is None  # dry_run -> no check
    check_calls = [c for c in mrun.call_args_list if c.args[0][1] == "check"]
    assert len(check_calls) == 0


def test_run_sync_skips_check_when_sync_failed(tmp_path):
    cfg = _make_cfg(tmp_path, post_sync_check=True)
    log_path = cfg.log_path

    def dispatch(argv, **kwargs):
        if argv[1] == "version":
            return _version_mock("1.70.0")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("", encoding="utf-8")
        # sync fails with exit 2 (not a transient code -> no retry)
        return MagicMock(returncode=2, stdout="", stderr="fatal error")

    with patch("sync.runner.shutil.which", return_value=FAKE_RCLONE), \
         patch("sync.runner.subprocess.run", side_effect=dispatch) as mrun, \
         _patch_audit():
        result = run_sync(cfg, rclone_bin=FAKE_RCLONE)

    assert result.success is False
    assert result.check_result is None  # failure -> no check
    check_calls = [c for c in mrun.call_args_list if c.args[0][1] == "check"]
    assert len(check_calls) == 0


def test_sync_result_audit_includes_check_summary(tmp_path):
    cr = CheckResult(ok=False, missing_local=1, missing_remote=0, differences=1)
    result = SyncResult(
        success=True, direction="pull", started_at=0.0, finished_at=1.0,
        rclone_exit_code=0, check_result=cr,
    )
    d = result.to_audit_dict()
    assert "check" in d
    assert d["check"]["ok"] is False
    assert d["check"]["differences"] == 1
