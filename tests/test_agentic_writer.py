"""Tests for agentic.writer -- the disabled/stubbed write gate.

Proves the triple-gate refuses every under-satisfied request, that a fully gated
request still only DRY-RUNS (never executes), and that the executor is unwired.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentic.config import AgenticConfig
from agentic.writer import EXECUTION_ENABLED, execute_write, plan_write
from utils.errors import AgenticError, AgenticWriteRefused
from utils.logger import reset_config_cache


@pytest.fixture(autouse=True)
def _temp_audit(tmp_path: Path):
    cfg = {"logging": {"audit_file": str(tmp_path / "audit.jsonl"), "audit_fields": {}},
           "policy": {"privacy": {}}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    reset_config_cache()
    from utils.logger import _get_config
    _get_config(str(path))
    yield
    reset_config_cache()


def _read_cfg() -> AgenticConfig:
    return AgenticConfig(mode="read", writes_enabled=False)


def _write_cfg() -> AgenticConfig:
    return AgenticConfig(mode="write", writes_enabled=True)


def test_execution_hard_disabled():
    assert EXECUTION_ENABLED is False


def test_refuses_when_not_write_mode():
    with pytest.raises(AgenticWriteRefused) as exc:
        plan_write(_read_cfg(), "pr_comment", "valid reason", confirm=True, number=1, body="hi")
    assert exc.value.details["failed_gate"] == "mode"


def test_refuses_when_writes_disabled():
    cfg = AgenticConfig(mode="write", writes_enabled=False)
    with pytest.raises(AgenticWriteRefused) as exc:
        plan_write(cfg, "pr_comment", "valid reason", confirm=True, number=1, body="hi")
    assert exc.value.details["failed_gate"] == "writes_enabled"


def test_refuses_when_reason_empty():
    with pytest.raises(AgenticWriteRefused) as exc:
        plan_write(_write_cfg(), "pr_comment", "   ", confirm=True, number=1, body="hi")
    assert exc.value.details["failed_gate"] == "reason"


def test_refuses_when_not_confirmed():
    with pytest.raises(AgenticWriteRefused) as exc:
        plan_write(_write_cfg(), "pr_comment", "valid reason", confirm=False, number=1, body="hi")
    assert exc.value.details["failed_gate"] == "confirm"


def test_unknown_op_raises():
    with pytest.raises(AgenticError):
        plan_write(_write_cfg(), "force_push", "valid reason", confirm=True)


def test_full_gate_returns_dryrun_only():
    plan = plan_write(_write_cfg(), "pr_comment", "explain the fix", confirm=True,
                      number=12, body="LGTM")
    assert plan["status"] == "dry_run_plan"
    assert plan["executed"] is False
    assert isinstance(plan["would_run"], list)
    assert "comment" in plan["would_run"]


def test_executor_refused_by_kill_switch():
    # EXECUTION_ENABLED is False (shipped state), so even a fully gate-satisfied
    # plan is refused at the execution boundary -- the kill switch is enforced,
    # not merely documented.
    plan = plan_write(_write_cfg(), "issue_comment", "explain", confirm=True,
                      number=1, body="note")
    with pytest.raises(AgenticWriteRefused) as exc:
        execute_write(plan)
    assert exc.value.details.get("failed_gate") == "execution_enabled"


def test_executor_unimplemented_even_with_flag_flipped(monkeypatch):
    # Flipping the flag is NOT sufficient to enable writes: the executor itself
    # is still unwired, so it raises NotImplementedError rather than running a gh
    # command. Enabling real writes remains a deliberate, separate change.
    # setattr via dotted string avoids importing agentic.writer a second way
    # (the module is already pulled in via `from agentic.writer import ...`).
    monkeypatch.setattr("agentic.writer.EXECUTION_ENABLED", True)
    plan = plan_write(_write_cfg(), "issue_comment", "explain", confirm=True,
                      number=1, body="note")
    with pytest.raises(NotImplementedError):
        execute_write(plan)
