"""Tests for agentic.sqlconnect.cli + selftest."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentic.sqlconnect import cli
from agentic.sqlconnect.selftest import run_self_test
from utils.logger import reset_config_cache


@pytest.fixture(autouse=True)
def _reset():
    reset_config_cache()
    yield
    reset_config_cache()


def _cfg(tmp_path: Path, block: dict) -> str:
    doc = {"logging": {"audit_file": str(tmp_path / "a.jsonl"), "audit_fields": {}}, "sqlconnect": block}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(path)


def test_status(tmp_path, capsys):
    cp = _cfg(tmp_path, {"enabled": False})
    assert cli.main(["--config", cp, "status"]) == 0
    assert "SQL Connector Status" in capsys.readouterr().out


def test_bad_config_exit_env(tmp_path):
    cp = _cfg(tmp_path, {"enabled": True, "driver": "oracle"})
    assert cli.main(["--config", cp, "status"]) == 3


def test_disabled_query_noop(tmp_path):
    cp = _cfg(tmp_path, {"enabled": False})
    assert cli.main(["--config", cp, "schema"]) == 0


def test_query_bad_sql_exit_fail(tmp_path):
    cp = _cfg(tmp_path, {"enabled": True})
    assert cli.main(["--config", cp, "query", "--sql", "DELETE FROM t"]) == 2


def test_query_good_sql_driver_absent_exit_env(tmp_path):
    cp = _cfg(tmp_path, {"enabled": True})
    # valid SELECT passes the guard, then the (absent) driver import -> EXIT_ENV
    assert cli.main(["--config", cp, "query", "--sql", "SELECT 1"]) == 3


def test_query_requires_arg(tmp_path):
    cp = _cfg(tmp_path, {"enabled": True})
    assert cli.main(["--config", cp, "query"]) == 2


def test_schema_driver_absent_exit_env(tmp_path):
    cp = _cfg(tmp_path, {"enabled": True})
    assert cli.main(["--config", cp, "schema"]) == 3


def test_test_command(tmp_path):
    cp = _cfg(tmp_path, {"enabled": True})
    assert cli.main(["--config", cp, "test"]) == 0


def test_selftest_all_pass(tmp_path):
    cp = _cfg(tmp_path, {"enabled": True})
    passed, total, lines = run_self_test(cp)
    assert total == 5 and passed == total
    assert "read-only guard rejects DML" in "\n".join(lines)


def test_selftest_bad_config(tmp_path):
    doc = {"logging": {"audit_file": str(tmp_path / "a.jsonl")}}  # no sqlconnect block
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    passed, total, lines = run_self_test(str(path))
    assert total == 5 and passed == total - 1
