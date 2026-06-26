"""Read-only SQL client scaffold (Postgres / MSSQL), disabled-by-default.

Read-only is enforced three ways: (1) a SELECT-only query guard rejects anything
that is not a single ``SELECT``/``WITH`` statement (no DDL/DML/multi-statement);
(2) the session is opened read-only at connect time; (3) ``allow_write`` is hard
False in v0.1. The DSN comes from an environment variable only -- never hardcoded.

Driver modules (``psycopg`` / ``pyodbc``) are imported lazily, so a disabled
connector never requires them. The actual connect/execute paths need a live DB and
are ``# pragma: no cover``; the query/identifier guards are pure and fully tested.

Never imported by gate.py / graph.py / mcp_hybrid_server.py.
"""

from __future__ import annotations

import os
import re
from typing import Any

from agentic.sqlconnect.config import SqlConnectConfig
from utils.errors import (
    SqlConnectError,
    SqlConnectRuntimeError,
    SqlDriverNotInstalledError,
)
from utils.logger import audit_log

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
_FORBIDDEN_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|merge|call|"
    r"exec|execute|into|copy|vacuum|attach|replace|begin|commit|rollback)\b",
    re.IGNORECASE,
)


def assert_read_only_sql(sql: str) -> str:
    """Return a cleaned single SELECT/WITH statement, or raise ``SqlConnectError``."""
    if not isinstance(sql, str) or not sql.strip():
        raise SqlConnectError("empty SQL", code="SQLCONNECT_BAD_QUERY")
    # Defense in depth: SQL comments (``--`` line, ``/* */`` block) are a known
    # vector for hiding forbidden keywords or a stacked statement from a keyword
    # scanner (the DB strips the comment, the guard does not). Read-only previews
    # never need comments, so reject them outright rather than try to parse them.
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise SqlConnectError(
            "SQL comments are not allowed in read-only queries",
            code="SQLCONNECT_BAD_QUERY",
        )
    cleaned = sql.strip().rstrip(";").strip()
    if ";" in cleaned:
        raise SqlConnectError(
            "multiple statements are not allowed", code="SQLCONNECT_BAD_QUERY"
        )
    lowered = cleaned.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise SqlConnectError(
            "only SELECT/WITH queries are allowed", code="SQLCONNECT_BAD_QUERY"
        )
    hit = _FORBIDDEN_RE.search(cleaned)
    if hit:
        raise SqlConnectError(
            f"forbidden keyword in read-only query: {hit.group(0)!r}",
            code="SQLCONNECT_BAD_QUERY", details={"keyword": hit.group(0)},
        )
    return cleaned


def validate_identifier(name: str) -> str:
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise SqlConnectError(
            f"invalid SQL identifier: {name!r}", code="SQLCONNECT_BAD_IDENT"
        )
    return name


def quote_identifier(name: str, driver: str) -> str:
    parts = validate_identifier(name).split(".")
    if driver == "mssql":
        return ".".join(f"[{p}]" for p in parts)
    return ".".join(f'"{p}"' for p in parts)


class SqlClient:
    """Read-only SQL client bound to a config's ``sqlconnect`` block."""

    def __init__(self, cfg: dict, sql_cfg: SqlConnectConfig, config_path: str = "config.yaml") -> None:
        self.cfg = cfg
        self.sql_cfg = sql_cfg
        self.config_path = config_path

    def _guard_op(self, op: str) -> None:
        if op not in self.sql_cfg.allowed_sql_ops:
            raise SqlConnectError(
                f"sql op {op!r} is not in allowed_sql_ops",
                code="SQLCONNECT_OP_NOT_ALLOWED",
                details={"op": op, "allowed": list(self.sql_cfg.allowed_sql_ops)},
            )

    def _dsn(self) -> str:
        dsn = os.environ.get(self.sql_cfg.dsn_env)
        if not dsn:
            raise SqlConnectRuntimeError(
                f"DSN env var {self.sql_cfg.dsn_env!r} is not set",
                details={"dsn_env": self.sql_cfg.dsn_env},
            )
        return dsn

    def _import_driver(self) -> Any:
        if self.sql_cfg.driver == "postgres":
            try:
                import psycopg  # noqa: PLC0415 -- lazy: disabled connector needs no driver
            except ImportError as exc:
                raise SqlDriverNotInstalledError(
                    "psycopg is not installed (pip install 'psycopg[binary]')",
                    details={"driver": "postgres"},
                ) from exc
            return psycopg
        try:
            import pyodbc  # noqa: PLC0415 -- lazy
        except ImportError as exc:
            raise SqlDriverNotInstalledError(
                "pyodbc is not installed (pip install pyodbc)",
                details={"driver": "mssql"},
            ) from exc
        return pyodbc

    def _apply_statement_timeout(self, conn: Any, cur: Any) -> None:
        """Enforce ``statement_timeout_ms`` on the session before the user query.

        Without this, a slow/pathological read-only SELECT (e.g. a cartesian join)
        runs unbounded -- the configured timeout would be a no-op. Driver-specific:
        Postgres applies a session GUC via ``set_config`` (parameterized -- ``SET``
        itself rejects bind params); MSSQL/pyodbc sets the per-query timeout on the
        connection (seconds). ``<= 0`` disables the cap explicitly.
        """
        timeout_ms = int(self.sql_cfg.statement_timeout_ms)
        if timeout_ms <= 0:
            return
        if self.sql_cfg.driver == "postgres":
            # SET statement_timeout cannot take a bind parameter; set_config can.
            cur.execute("SELECT set_config('statement_timeout', %s, false)", (str(timeout_ms),))
        else:  # mssql / pyodbc: query timeout is in seconds on the connection
            with suppress_attr_error():
                conn.timeout = max(1, timeout_ms // 1000)

    def _execute(self, sql: str, params: tuple = ()) -> dict:  # pragma: no cover - needs live DB
        driver = self._import_driver()
        dsn = self._dsn()
        conn = driver.connect(dsn)
        try:
            with suppress_attr_error():
                conn.read_only = True
            cur = conn.cursor()
            self._apply_statement_timeout(conn, cur)
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(self.sql_cfg.max_rows + 1)
            truncated = len(rows) > self.sql_cfg.max_rows
            rows = rows[: self.sql_cfg.max_rows]
            return {
                "columns": cols,
                "rows": [list(r) for r in rows],
                "row_count": len(rows),
                "truncated": truncated,
            }
        finally:
            conn.close()

    def schema_list(self) -> dict:
        self._guard_op("schema_list")
        audit_log({"event": "sqlconnect_read", "op": "schema_list"}, self.config_path)
        sql = (
            "SELECT table_schema, table_name FROM information_schema.tables "
            "ORDER BY table_schema, table_name"
        )
        return {"op": "schema_list", **self._execute(sql)}

    def table_preview(self, table: str) -> dict:
        self._guard_op("table_preview")
        ident = quote_identifier(table, self.sql_cfg.driver)
        audit_log({"event": "sqlconnect_read", "op": "table_preview", "table": table}, self.config_path)
        # ident is allow-list-validated + quoted (validate_identifier/quote_identifier)
        # and max_rows is coerced to int; no untrusted text reaches the SQL string.
        if self.sql_cfg.driver == "mssql":
            sql = f"SELECT TOP {int(self.sql_cfg.max_rows)} * FROM {ident}"  # noqa: S608
        else:
            sql = f"SELECT * FROM {ident} LIMIT {int(self.sql_cfg.max_rows)}"  # noqa: S608
        return {"op": "table_preview", "table": table, **self._execute(sql)}

    def run_select(self, sql: str) -> dict:
        self._guard_op("run_select")
        cleaned = assert_read_only_sql(sql)  # pure guard, runs before any connection
        audit_log({"event": "sqlconnect_read", "op": "run_select"}, self.config_path)
        return {"op": "run_select", **self._execute(cleaned)}


class suppress_attr_error:  # pragma: no cover - trivial helper used only in live path
    """Context manager: ignore AttributeError when a driver lacks ``read_only``."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, *_: object) -> bool:
        return exc_type is AttributeError


__all__ = ["SqlClient", "assert_read_only_sql", "validate_identifier", "quote_identifier"]
