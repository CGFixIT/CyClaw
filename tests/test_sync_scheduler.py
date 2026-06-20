"""Self-contained tests for sync.scheduler.

Runnable with ``pytest --noconftest`` (no conftest fixtures): builds an
``RcloneConfig`` directly via a tmp config.yaml + ``reset_config_cache`` and
patches the subprocess / which / platform boundary. No real crontab or schtasks
is ever invoked, and no network is touched.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sync.config import RcloneConfig, load_sync_config
from sync.scheduler import (
    TASK_TAG,
    WINDOWS_TASK_NAME,
    CronScheduler,
    ScheduleEntry,
    WindowsTaskScheduler,
    get_scheduler,
)
from utils.errors import SchedulerError
from utils.logger import reset_config_cache

# A repo-valid corpus path: config validation requires local_path to resolve
# under the repo's data/corpus tree, so derive it from this file's location.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CORPUS = str(_REPO_ROOT / "data" / "corpus")


def _make_cfg(schedule_hour: int = 2, schedule_min: int = 0) -> RcloneConfig:
    return RcloneConfig(
        local_path=_CORPUS,
        remote_name="dropbox_cyclaw",
        remote_path="CyClaw/corpus",
        schedule_hour=schedule_hour,
        schedule_min=schedule_min,
    )


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# get_scheduler factory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("system", "expected"),
    [
        ("Linux", CronScheduler),
        ("Darwin", CronScheduler),
        ("Windows", WindowsTaskScheduler),
    ],
)
def test_get_scheduler_returns_right_class(system: str, expected: type) -> None:
    cfg = _make_cfg()
    with patch("sync.scheduler.platform.system", return_value=system):
        sched = get_scheduler(cfg)
    assert isinstance(sched, expected)


def test_get_scheduler_unsupported_platform_raises() -> None:
    cfg = _make_cfg()
    with patch("sync.scheduler.platform.system", return_value="Plan9"):
        with pytest.raises(SchedulerError):
            get_scheduler(cfg)


# ---------------------------------------------------------------------------
# CronScheduler.install
# ---------------------------------------------------------------------------


def test_cron_install_appends_exactly_one_tagged_line() -> None:
    cfg = _make_cfg(schedule_hour=3, schedule_min=15)
    existing = "0 1 * * * /usr/bin/backup.sh\n"
    written: dict[str, str] = {}

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        if argv[1] == "-l":
            return _completed(stdout=existing)
        # write path: crontab -
        written["content"] = kwargs["input"]
        return _completed()

    with (
        patch("sync.scheduler.shutil.which", return_value="/usr/bin/crontab"),
        patch("sync.scheduler.subprocess.run", side_effect=fake_run),
        patch("sync.scheduler.platform.system", return_value="Linux"),
    ):
        entry = CronScheduler(cfg).install()

    content = written["content"]
    tagged = [ln for ln in content.splitlines() if TASK_TAG in ln]
    assert len(tagged) == 1
    # User's unrelated line is preserved.
    assert "/usr/bin/backup.sh" in content
    assert isinstance(entry, ScheduleEntry)
    assert entry.cron_or_time == "15 3 * * *"
    assert tagged[0].startswith("15 3 * * *")
    assert tagged[0].endswith(f"# {TASK_TAG}")
    # Command cd's into the repo root, not data/corpus.
    assert "-m sync.cli sync" in tagged[0]
    assert os.path.basename(_REPO_ROOT) in tagged[0]


def test_cron_install_replaces_prior_tagged_line() -> None:
    cfg = _make_cfg()
    # Two existing tagged lines plus an unrelated one.
    existing = (
        "0 1 * * * /usr/bin/keep.sh\n"
        f"9 9 * * * old-cmd # {TASK_TAG}\n"
        f"8 8 * * * older-cmd # {TASK_TAG}\n"
    )
    written: dict[str, str] = {}

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        if argv[1] == "-l":
            return _completed(stdout=existing)
        written["content"] = kwargs["input"]
        return _completed()

    with (
        patch("sync.scheduler.shutil.which", return_value="/usr/bin/crontab"),
        patch("sync.scheduler.subprocess.run", side_effect=fake_run),
        patch("sync.scheduler.platform.system", return_value="Linux"),
    ):
        CronScheduler(cfg).install()

    content = written["content"]
    tagged = [ln for ln in content.splitlines() if TASK_TAG in ln]
    assert len(tagged) == 1  # both old tagged lines stripped, one fresh appended
    assert "old-cmd" not in content
    assert "older-cmd" not in content
    assert "/usr/bin/keep.sh" in content


# ---------------------------------------------------------------------------
# CronScheduler.remove
# ---------------------------------------------------------------------------


def test_cron_remove_returns_false_when_no_tagged_line() -> None:
    cfg = _make_cfg()
    existing = "0 1 * * * /usr/bin/keep.sh\n"
    write_called = {"n": 0}

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        if argv[1] == "-l":
            return _completed(stdout=existing)
        write_called["n"] += 1
        return _completed()

    with (
        patch("sync.scheduler.shutil.which", return_value="/usr/bin/crontab"),
        patch("sync.scheduler.subprocess.run", side_effect=fake_run),
    ):
        result = CronScheduler(cfg).remove()

    assert result is False
    assert write_called["n"] == 0  # nothing rewritten when nothing matched


def test_cron_remove_returns_true_when_tagged_line_present() -> None:
    cfg = _make_cfg()
    existing = "0 1 * * * /usr/bin/keep.sh\n" f"2 2 * * * some-cmd # {TASK_TAG}\n"
    written: dict[str, str] = {}

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        if argv[1] == "-l":
            return _completed(stdout=existing)
        written["content"] = kwargs["input"]
        return _completed()

    with (
        patch("sync.scheduler.shutil.which", return_value="/usr/bin/crontab"),
        patch("sync.scheduler.subprocess.run", side_effect=fake_run),
    ):
        result = CronScheduler(cfg).remove()

    assert result is True
    assert TASK_TAG not in written["content"]
    assert "/usr/bin/keep.sh" in written["content"]


# ---------------------------------------------------------------------------
# CronScheduler.status
# ---------------------------------------------------------------------------


def test_cron_status_parses_tagged_line() -> None:
    cfg = _make_cfg()
    existing = "0 1 * * * /usr/bin/keep.sh\n" f'30 4 * * * cd "/repo" && python -m sync.cli sync # {TASK_TAG}\n'

    with (
        patch("sync.scheduler.shutil.which", return_value="/usr/bin/crontab"),
        patch("sync.scheduler.subprocess.run", return_value=_completed(stdout=existing)),
        patch("sync.scheduler.platform.system", return_value="Linux"),
    ):
        entry = CronScheduler(cfg).status()

    assert entry is not None
    assert entry.cron_or_time == "30 4 * * *"
    assert "sync.cli sync" in entry.command
    assert TASK_TAG not in entry.command  # comment stripped from the command


def test_cron_status_returns_none_when_no_tagged_line() -> None:
    cfg = _make_cfg()
    existing = "0 1 * * * /usr/bin/keep.sh\n"
    with (
        patch("sync.scheduler.shutil.which", return_value="/usr/bin/crontab"),
        patch("sync.scheduler.subprocess.run", return_value=_completed(stdout=existing)),
    ):
        assert CronScheduler(cfg).status() is None


def test_cron_missing_crontab_binary_raises() -> None:
    cfg = _make_cfg()
    with patch("sync.scheduler.shutil.which", return_value=None):
        with pytest.raises(SchedulerError):
            CronScheduler(cfg).status()


def test_cron_uses_argv_list_never_shell() -> None:
    cfg = _make_cfg()
    seen: list[object] = []

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(argv)
        assert isinstance(argv, list)
        assert "shell" not in kwargs or kwargs["shell"] is False
        if argv[1] == "-l":
            return _completed(stdout="")
        return _completed()

    with (
        patch("sync.scheduler.shutil.which", return_value="/usr/bin/crontab"),
        patch("sync.scheduler.subprocess.run", side_effect=fake_run),
        patch("sync.scheduler.platform.system", return_value="Linux"),
    ):
        CronScheduler(cfg).install()

    assert seen  # at least one call made
    for argv in seen:
        assert isinstance(argv, list)
        assert argv[0] == "/usr/bin/crontab"


# ---------------------------------------------------------------------------
# WindowsTaskScheduler
# ---------------------------------------------------------------------------


def test_windows_install_builds_schtasks_argv() -> None:
    cfg = _make_cfg(schedule_hour=5, schedule_min=7)
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _completed(stdout="SUCCESS")

    with (
        patch("sync.scheduler.shutil.which", return_value=r"C:\Windows\System32\schtasks.exe"),
        patch("sync.scheduler.subprocess.run", side_effect=fake_run),
        patch("sync.scheduler.platform.system", return_value="Windows"),
    ):
        entry = WindowsTaskScheduler(cfg).install()

    argv = captured["argv"]
    assert isinstance(argv, list)
    assert "shell" not in captured["kwargs"] or captured["kwargs"]["shell"] is False
    assert argv[0] == r"C:\Windows\System32\schtasks.exe"
    assert "/Create" in argv
    assert argv[argv.index("/TN") + 1] == WINDOWS_TASK_NAME
    assert argv[argv.index("/SC") + 1] == "DAILY"
    assert argv[argv.index("/ST") + 1] == "05:07"
    assert "/F" in argv
    assert argv[argv.index("/RL") + 1] == "LIMITED"
    assert entry.cron_or_time == "05:07"
    assert entry.platform_name == "windows"


def test_windows_remove_not_found_returns_false() -> None:
    cfg = _make_cfg()
    with (
        patch("sync.scheduler.shutil.which", return_value=r"C:\Windows\System32\schtasks.exe"),
        patch(
            "sync.scheduler.subprocess.run",
            return_value=_completed(returncode=1, stderr="ERROR: The system cannot find the file specified."),
        ),
    ):
        assert WindowsTaskScheduler(cfg).remove() is False


def test_windows_remove_success_returns_true() -> None:
    cfg = _make_cfg()
    with (
        patch("sync.scheduler.shutil.which", return_value=r"C:\Windows\System32\schtasks.exe"),
        patch("sync.scheduler.subprocess.run", return_value=_completed(returncode=0, stdout="SUCCESS")),
    ):
        assert WindowsTaskScheduler(cfg).remove() is True


def test_windows_missing_schtasks_raises() -> None:
    cfg = _make_cfg()
    with patch("sync.scheduler.shutil.which", return_value=None):
        with pytest.raises(SchedulerError):
            WindowsTaskScheduler(cfg).install()


# ---------------------------------------------------------------------------
# Config-from-yaml path (Appendix D style, no conftest fixtures)
# ---------------------------------------------------------------------------


def test_scheduler_from_loaded_config(tmp_path: Path) -> None:
    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text(
        "sync:\n"
        "  enabled: true\n"
        f'  local_path: "{_CORPUS}"\n'
        "  remote_name: dropbox_cyclaw\n"
        "  remote_path: CyClaw/corpus\n"
        "  schedule_hour: 6\n"
        "  schedule_min: 30\n"
    )
    reset_config_cache()
    try:
        cfg = load_sync_config(str(cfg_yaml))
    finally:
        reset_config_cache()

    with patch("sync.scheduler.platform.system", return_value="Linux"):
        sched = get_scheduler(cfg)
    assert isinstance(sched, CronScheduler)
    assert sched.cfg.schedule_hour == 6
    assert sched.cfg.schedule_min == 30
