"""Tests for guardrails.selftest -- the operator pre-flight check runner.

Focus: the reported pass/total is consistent across the success and the
config-failure paths (the failure path previously reported 6 checks, the
success path 7).
"""

from __future__ import annotations

from guardrails import selftest
from guardrails.errors import GuardrailsConfigError


def test_self_test_reports_seven_checks():
    """The normal run always enumerates the full 7-check ladder."""
    passed, total, lines = selftest.run_self_test()
    assert total == 7
    assert len(lines) == 7
    assert 0 <= passed <= total


def test_self_test_total_consistent_on_config_failure(monkeypatch):
    """A config error must not shrink the denominator (was 6 before the fix)."""

    def _boom(config_path: str = "config.yaml"):
        raise GuardrailsConfigError("invalid guardrails block")

    monkeypatch.setattr(selftest, "load_guardrails_config", _boom)
    passed, total, lines = selftest.run_self_test()

    assert total == 7
    assert len(lines) == 7
    # Check 01 is the real failure; 02..07 are skips, which count as passed.
    assert "[FAIL] 01" in lines[0]
    assert any("07." in ln for ln in lines)
    assert passed == 6
