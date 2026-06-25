"""Tests for utils.ops_runner — the subprocess shim behind /ops/sync and /ops/agentic.

These never spawn the real CLIs: ``_run`` is monkeypatched to capture the argv the
shim builds and to return a synthetic ``CompletedProcess``. The one exception is the
isolation test, which spins a clean interpreter to prove importing the shim never
imports the out-of-band packages.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from utils import ops_runner
from utils.ops_runner import OpsError, run_agentic_op, run_sync_op


def _fake_run(returncode: int = 0, stdout: str = "", stderr: str = ""):
    """Return a (_run replacement, captured-argv list) pair."""
    captured: list[list[str]] = []

    def _runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        captured.append(argv)
        return subprocess.CompletedProcess(args=argv, returncode=returncode, stdout=stdout, stderr=stderr)

    return _runner, captured


# --------------------------------------------------------------------------- sync


def test_sync_unknown_action_raises() -> None:
    with pytest.raises(OpsError):
        run_sync_op("rm-rf")


def test_sync_status_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _fake_run(returncode=0, stdout="ok")
    monkeypatch.setattr(ops_runner, "_run", runner)
    res = run_sync_op("status")
    argv = captured[0]
    assert argv[0] == sys.executable
    assert argv[1:3] == ["-m", "sync.cli"]
    assert "--config" in argv and argv[-1] == "status"
    assert res.ok is True and res.label == "ok" and res.exit_code == 0


def test_sync_dry_run_appends_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _fake_run()
    monkeypatch.setattr(ops_runner, "_run", runner)
    run_sync_op("sync", dry_run=True)
    assert captured[0][-1] == "--dry-run"
    assert captured[0][-2] == "sync"


def test_sync_dry_run_ignored_for_non_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _fake_run()
    monkeypatch.setattr(ops_runner, "_run", runner)
    run_sync_op("status", dry_run=True)  # dry_run must NOT leak onto status
    assert "--dry-run" not in captured[0]


@pytest.mark.parametrize(
    "code,ok,label",
    [(0, True, "ok"), (10, True, "ok_reindex_needed"), (1, False, "safety_abort"),
     (2, False, "failed"), (3, False, "env_config"), (99, False, "unknown")],
)
def test_sync_exit_code_labels(monkeypatch: pytest.MonkeyPatch, code: int, ok: bool, label: str) -> None:
    runner, _ = _fake_run(returncode=code, stderr="boom" if code else "")
    monkeypatch.setattr(ops_runner, "_run", runner)
    res = run_sync_op("sync")
    assert res.ok is ok and res.label == label and res.exit_code == code


# ------------------------------------------------------------------------- agentic


def test_agentic_unknown_action_raises() -> None:
    with pytest.raises(OpsError):
        run_agentic_op("delete-repo")


def test_agentic_context_repo_default(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _fake_run(returncode=0, stdout='{"repo": "x"}')
    monkeypatch.setattr(ops_runner, "_run", runner)
    res = run_agentic_op("context")
    assert "--repo" in captured[0]
    assert res.parsed == {"repo": "x"}  # JSON action parsed on success


def test_agentic_context_pr_and_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _fake_run(returncode=0, stdout="{}")
    monkeypatch.setattr(ops_runner, "_run", runner)
    run_agentic_op("context", pr=42)
    assert captured[0][-2:] == ["--pr", "42"]
    captured.clear()
    run_agentic_op("context", issue=7, no_diff=True)
    assert "--issue" in captured[0] and "7" in captured[0] and "--no-diff" in captured[0]


def test_agentic_propose_requires_name_desc() -> None:
    with pytest.raises(OpsError):
        run_agentic_op("propose-skill", name="x")  # missing desc


def test_agentic_apply_requires_reason() -> None:
    with pytest.raises(OpsError):
        run_agentic_op("apply-skill", name="x", desc="y", reason="   ")


def test_agentic_apply_confirm_and_body_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    runner, captured = _fake_run(returncode=0, stdout='{"status": "applied"}')
    monkeypatch.setattr(ops_runner, "_run", runner)
    res = run_agentic_op(
        "apply-skill", name="demo", desc="a demo skill", body="# body\ncontent",
        reason="adding demo", confirm=True,
    )
    argv = captured[0]
    assert "--name" in argv and "demo" in argv
    assert "--confirm" in argv
    # body routed through a temp --body-file, never inlined as an argv token
    assert "--body-file" in argv
    body_idx = argv.index("--body-file") + 1
    assert "# body" not in argv  # the literal body is not on the command line
    # the temp file is cleaned up after the run
    from pathlib import Path
    assert not Path(argv[body_idx]).exists()
    assert res.parsed == {"status": "applied"}


def test_agentic_apply_body_file_cleaned_up_when_run_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # run_agentic_op's docstring promises the temp --body-file is unlinked on
    # EVERY exit path, "return or raise". Only the return path was covered; this
    # locks in the finally-block cleanup when _run raises (e.g. the CLI hangs and
    # subprocess.TimeoutExpired fires) so a crashing op cannot leak skill-body
    # temp files into the OS temp dir on repeated failures.
    from pathlib import Path

    captured: list[list[str]] = []

    def _boom(argv: list[str]) -> subprocess.CompletedProcess[str]:
        captured.append(argv)
        raise subprocess.TimeoutExpired(cmd=argv, timeout=1)

    monkeypatch.setattr(ops_runner, "_run", _boom)

    with pytest.raises(subprocess.TimeoutExpired):
        run_agentic_op(
            "apply-skill", name="demo", desc="a demo skill", body="# body\ncontent",
            reason="adding demo", confirm=True,
        )

    # The body-file was created and handed to _run, then unlinked by the finally
    # block despite _run raising.
    argv = captured[0]
    body_file = argv[argv.index("--body-file") + 1]
    assert not Path(body_file).exists()


def test_agentic_apply_no_confirm_omits_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _fake_run(returncode=4, stderr="apply-skill requires --confirm")
    monkeypatch.setattr(ops_runner, "_run", runner)
    res = run_agentic_op("apply-skill", name="x", desc="y", reason="r", confirm=False)
    assert "--confirm" not in captured[0]
    assert res.exit_code == 4 and res.label == "write_refused" and res.ok is False


@pytest.mark.parametrize(
    "code,ok,label",
    [(0, True, "ok"), (2, False, "failed"), (3, False, "env_config"),
     (4, False, "write_refused"), (77, False, "unknown")],
)
def test_agentic_exit_code_labels(monkeypatch: pytest.MonkeyPatch, code: int, ok: bool, label: str) -> None:
    runner, _ = _fake_run(returncode=code, stdout="{}" if code == 0 else "")
    monkeypatch.setattr(ops_runner, "_run", runner)
    res = run_agentic_op("status")
    assert res.ok is ok and res.label == label


def test_agentic_text_action_not_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    # status emits human text, not JSON — parsed must stay None even on success.
    runner, _ = _fake_run(returncode=0, stdout="  enabled... False")
    monkeypatch.setattr(ops_runner, "_run", runner)
    res = run_agentic_op("status")
    assert res.parsed is None


def test_to_dict_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _ = _fake_run(returncode=0, stdout="ok")
    monkeypatch.setattr(ops_runner, "_run", runner)
    d = run_sync_op("status").to_dict()
    assert set(d) == {"subsystem", "action", "exit_code", "ok", "label", "stdout", "stderr", "parsed"}


# ----------------------------------------------------------------------- isolation


def test_importing_shim_does_not_import_out_of_band_packages() -> None:
    """Hard invariant: importing the shim must not import sync/ or agentic/.

    Run in a clean interpreter so prior test imports cannot mask a regression.
    """
    code = (
        "import sys; import utils.ops_runner; "
        "assert 'sync' not in sys.modules, 'ops_runner imported sync'; "
        "assert 'agentic' not in sys.modules, 'ops_runner imported agentic'; "
        "print('ISOLATED_OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ops_runner._REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ISOLATED_OK" in proc.stdout
