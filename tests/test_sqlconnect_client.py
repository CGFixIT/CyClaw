"""Tests for agentic.sqlconnect.client guards (pure) + driver/DSN handling."""

from __future__ import annotations

import pytest

from agentic.sqlconnect.client import (
    SqlClient,
    assert_read_only_sql,
    quote_identifier,
    validate_identifier,
)
from agentic.sqlconnect.config import SqlConnectConfig
from utils.errors import (
    SqlConnectError,
    SqlConnectRuntimeError,
    SqlDriverNotInstalledError,
)


def test_assert_accepts_select_and_with():
    assert assert_read_only_sql("SELECT 1") == "SELECT 1"
    assert assert_read_only_sql("  with t as (select 1) select * from t ;").startswith("with")


@pytest.mark.parametrize("bad", [
    "DELETE FROM users",
    "DROP TABLE t",
    "INSERT INTO t VALUES (1)",
    "UPDATE t SET x=1",
    "SELECT 1; DROP TABLE t",
    "SELECT * INTO newt FROM t",
    "EXEC sp_who",
    "",
])
def test_assert_rejects_non_readonly(bad):
    with pytest.raises(SqlConnectError):
        assert_read_only_sql(bad)


def test_validate_identifier():
    assert validate_identifier("schema.table") == "schema.table"
    for bad in ("1bad", "a;b", "a-b", "drop table"):
        with pytest.raises(SqlConnectError):
            validate_identifier(bad)


def test_quote_identifier_per_driver():
    assert quote_identifier("s.t", "postgres") == '"s"."t"'
    assert quote_identifier("s.t", "mssql") == "[s].[t]"


def test_op_guard():
    sc = SqlConnectConfig(allowed_sql_ops=["schema_list"])
    client = SqlClient({}, sc)
    with pytest.raises(SqlConnectError):
        client.run_select("SELECT 1")


def test_run_select_bad_sql_before_connect():
    sc = SqlConnectConfig()
    client = SqlClient({}, sc)
    with pytest.raises(SqlConnectError):
        client.run_select("DELETE FROM t")  # guard fires before any DB work


def test_driver_absent():
    sc = SqlConnectConfig(driver="postgres")
    client = SqlClient({}, sc)
    with pytest.raises(SqlDriverNotInstalledError):
        client._import_driver()  # psycopg not installed in this env


def test_dsn_missing(monkeypatch):
    sc = SqlConnectConfig()
    monkeypatch.delenv(sc.dsn_env, raising=False)
    client = SqlClient({}, sc)
    with pytest.raises(SqlConnectRuntimeError):
        client._dsn()
