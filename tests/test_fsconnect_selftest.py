"""Tests for agentic.fsconnect.selftest -- pre-flight smoke (POSIX)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from agentic.fsconnect.selftest import run_self_test
from utils.logger import reset_config_cache

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX temp-dir checks")


@pytest.fixture(autouse=True)
def _reset():
    reset_config_cache()
    yield
    reset_config_cache()


def _cfg(tmp_path: Path, fsblock: dict | None) -> str:
    doc: dict = {
        "logging": {"audit_file": str(tmp_path / "audit.jsonl"), "audit_fields": {}},
        "policy": {"prompt_filter": {"banned_patterns": ["ignore previous instructions"]}, "privacy": {}},
    }
    if fsblock is not None:
        doc["fsconnect"] = fsblock
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(path)


def test_all_checks_pass(tmp_path):
    path = _cfg(tmp_path, {"enabled": True, "allowed_roots": [str(tmp_path)]})
    passed, total, lines = run_self_test(path)
    assert total == 5
    assert passed == total
    joined = "\n".join(lines)
    assert "path guard denies" in joined
    assert "write gate refuses" in joined


def test_bad_config_fails_first_skips_rest(tmp_path):
    path = _cfg(tmp_path, None)  # no fsconnect block
    passed, total, lines = run_self_test(path)
    assert total == 5
    assert passed == total - 1
    assert "no config" in "\n".join(lines).lower()
