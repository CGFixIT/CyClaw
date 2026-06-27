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
    # SQL comments are a stacked-statement / keyword-hiding vector and are refused.
    "SELECT 1 -- harmless",
    "SELECT 1 /* DROP TABLE t */",
    "SELECT 1 /* ; */ FROM t",
])
def test_assert_rejects_non_readonly(bad):
    with pytest.raises(SqlConnectError):
        assert_read_only_sql(bad)


@pytest.mark.parametrize("good", [
    "SELECT replace(name, 'a', 'b') FROM t",
    "select id, REPLACE(path, '\\\\', '/') as p from files",
    "WITH x AS (SELECT replace(c, ' ', '_') AS c FROM t) SELECT * FROM x",
])
def test_assert_allows_replace_read_function(good):
    """``replace()`` is a read-only scalar in Postgres/MSSQL and must not be blocked."""
    assert assert_read_only_sql(good).lower().startswith(("select", "with"))


@pytest.mark.parametrize("good", [
    # String literals / quoted identifiers may legitimately contain SQL keywords
    # or punctuation -- they are data / column names, not executable statements.
    "SELECT 'please do not delete' AS note",
    "SELECT * FROM t WHERE name = 'create account'",
    'SELECT "delete" FROM t',                 # forbidden word as a quoted identifier
    "SELECT 'a;b' AS x",                       # semicolon inside a literal is not a 2nd statement
    "SELECT 'rate is 5/*2' AS note",          # comment marker inside a literal is just data
    "SELECT 'it''s fine' AS note",            # doubled-quote escape inside a literal
])
def test_assert_allows_keywords_inside_quoted_literals(good):
    """A keyword/punctuation inside a quoted literal or identifier must not be blocked."""
    assert assert_read_only_sql(good).lower().startswith(("select", "with"))


@pytest.mark.parametrize("bad", [
    # The classic CTE-DML bypass: starts with WITH but performs a write. The DML
    # keyword is OUTSIDE quotes, so quote-stripping must not let it through.
    "WITH t AS (DELETE FROM users RETURNING *) SELECT * FROM t",
    "WITH t AS (UPDATE users SET x=1 RETURNING *) SELECT * FROM t",
    "WITH t AS (INSERT INTO users VALUES (1) RETURNING *) SELECT * FROM t",
    # Stacked statement / real comment outside quotes still caught after stripping.
    "SELECT * FROM t; DROP TABLE x",
    "SELECT * FROM t -- DROP TABLE x",
])
def test_assert_still_rejects_dml_outside_quotes(bad):
    """Quote-stripping must not reopen the CTE-DML / stacked-statement vectors."""
    with pytest.raises(SqlConnectError):
        assert_read_only_sql(bad)


def test_assert_rejects_comments_with_specific_code():
    """Comment rejection fires before the keyword/multi-statement guards."""
    with pytest.raises(SqlConnectError) as exc:
        assert_read_only_sql("SELECT * FROM t -- /* sneaky */ DROP TABLE x")
    assert exc.value.code == "SQLCONNECT_BAD_QUERY"
    assert "comment" in str(exc.value).lower()


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


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple] = []
        self.description = [("col",)]

    def execute(self, sql, params=()) -> None:
        self.executed.append((sql, params))

    def fetchmany(self, n):
        return [("v",)]


class _FakeConn:
    def __init__(self) -> None:
        self.read_only = False
        self.timeout = None
        self.cur = _FakeCursor()

    def cursor(self):
        return self.cur

    def close(self) -> None:
        pass


class _FakeDriver:
    def __init__(self) -> None:
        self.conn = _FakeConn()

    def connect(self, dsn):
        return self.conn


def test_execute_applies_statement_timeout_postgres(monkeypatch):
    sc = SqlConnectConfig(driver="postgres", statement_timeout_ms=7000)
    monkeypatch.setenv(sc.dsn_env, "postgresql://x")
    client = SqlClient({}, sc)
    fake = _FakeDriver()
    monkeypatch.setattr(client, "_import_driver", lambda: fake)
    client._execute("SELECT 1")
    # The timeout is applied via set_config BEFORE the user query runs.
    first_sql, first_params = fake.conn.cur.executed[0]
    assert "set_config" in first_sql.lower()
    assert "statement_timeout" in first_sql.lower()
    assert first_params == ("7000",)
    assert fake.conn.cur.executed[1][0] == "SELECT 1"


def test_execute_applies_query_timeout_mssql(monkeypatch):
    sc = SqlConnectConfig(driver="mssql", statement_timeout_ms=8000)
    monkeypatch.setenv(sc.dsn_env, "Driver=ODBC;")
    client = SqlClient({}, sc)
    fake = _FakeDriver()
    monkeypatch.setattr(client, "_import_driver", lambda: fake)
    client._execute("SELECT 1")
    # MSSQL uses the connection query timeout (seconds), not a SET statement.
    assert fake.conn.timeout == 8
    assert not any("statement_timeout" in s.lower() for s, _ in fake.conn.cur.executed)


def test_execute_timeout_disabled_when_non_positive(monkeypatch):
    sc = SqlConnectConfig(driver="postgres")
    sc.statement_timeout_ms = 0  # bypass post-init validation to exercise the disabled branch
    monkeypatch.setenv(sc.dsn_env, "postgresql://x")
    client = SqlClient({}, sc)
    fake = _FakeDriver()
    monkeypatch.setattr(client, "_import_driver", lambda: fake)
    client._execute("SELECT 1")
    # No timeout SET issued; only the user query runs.
    assert fake.conn.cur.executed == [("SELECT 1", ())]
