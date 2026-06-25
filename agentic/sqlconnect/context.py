"""Thin read bundlers over :class:`agentic.sqlconnect.client.SqlClient`."""

from __future__ import annotations

from agentic.sqlconnect.client import SqlClient
from agentic.sqlconnect.config import SqlConnectConfig


def run_op(
    cfg: dict,
    sql_cfg: SqlConnectConfig,
    op: str,
    *,
    config_path: str = "config.yaml",
    table: str | None = None,
    sql: str | None = None,
) -> dict:
    client = SqlClient(cfg, sql_cfg, config_path=config_path)
    if op == "schema_list":
        return client.schema_list()
    if op == "table_preview":
        return client.table_preview(table or "")
    if op == "run_select":
        return client.run_select(sql or "")
    raise ValueError(f"unknown sql op: {op!r}")


__all__ = ["run_op"]
