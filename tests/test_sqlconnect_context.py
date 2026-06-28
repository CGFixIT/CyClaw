"""Tests for agentic.sqlconnect.context.run_op -- the read-op dispatcher.

run_op routes a SQL op string to the matching SqlClient method and raises on an
unknown op. Nothing else in the suite imported this module, so its dispatch
branches, the ``table or ""`` / ``sql or ""`` coalescing, and the unknown-op
fall-through were untested. SqlClient is mocked here -- no live DB or driver.
"""

from __future__ import annotations

import pytest

from agentic.sqlconnect import context

# run_op only passes sql_cfg through to the (mocked) SqlClient, so a sentinel is
# enough -- this avoids coupling the test to SqlConnectConfig's constructor.
_SQL_CFG = object()


class _FakeClient:
    def __init__(self, cfg, sql_cfg, config_path="config.yaml"):
        self.config_path = config_path

    def schema_list(self):
        return {"op": "schema_list"}

    def table_preview(self, table):
        return {"op": "table_preview", "table": table}

    def run_select(self, sql):
        return {"op": "run_select", "sql": sql}


@pytest.fixture
def patched(monkeypatch):
    captured: dict = {}

    def factory(cfg, sql_cfg, config_path="config.yaml"):
        client = _FakeClient(cfg, sql_cfg, config_path)
        captured["client"] = client
        return client

    monkeypatch.setattr(context, "SqlClient", factory)
    return captured


def test_schema_list_routes(patched):
    assert context.run_op({}, _SQL_CFG, "schema_list") == {"op": "schema_list"}


def test_table_preview_routes_with_table(patched):
    res = context.run_op({}, _SQL_CFG, "table_preview", table="public.users")
    assert res == {"op": "table_preview", "table": "public.users"}


def test_table_preview_coalesces_missing_table(patched):
    # table=None must coalesce to "" (the client's identifier guard handles empties),
    # never reach the method as None.
    assert context.run_op({}, _SQL_CFG, "table_preview")["table"] == ""


def test_run_select_routes_with_sql(patched):
    res = context.run_op({}, _SQL_CFG, "run_select", sql="SELECT 1")
    assert res == {"op": "run_select", "sql": "SELECT 1"}


def test_run_select_coalesces_missing_sql(patched):
    assert context.run_op({}, _SQL_CFG, "run_select")["sql"] == ""


def test_unknown_op_raises(patched):
    with pytest.raises(ValueError, match="unknown sql op"):
        context.run_op({}, _SQL_CFG, "delete_everything")


def test_config_path_threaded_to_client(patched):
    context.run_op({}, _SQL_CFG, "schema_list", config_path="/x/config.yaml")
    assert patched["client"].config_path == "/x/config.yaml"
