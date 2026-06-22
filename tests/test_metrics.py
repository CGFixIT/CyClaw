"""Unit tests for metrics.py — audit.jsonl parsing + reporting.

Focus: the retrieval-mode breakdown must count BOTH audit event shapes.
The graph audit path writes the mode under ``retrieval_mode``; the MCP server
(``mcp_hybrid_server._handle_search``) writes it under ``mode``. A regression
here previously bucketed every ``mcp_rag_query`` as "unknown".
"""

import json

import yaml

import metrics
from metrics import load_events, print_metrics


def _write_audit(tmp_path, events):
    audit_file = tmp_path / "audit.jsonl"
    with open(audit_file, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    return str(audit_file)


def _write_config(tmp_path, audit_file):
    cfg = {"logging": {"audit_file": audit_file}}
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f)
    return str(config_path)


class TestLoadEvents:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_events(str(tmp_path / "nope.jsonl")) == []

    def test_skips_malformed_lines(self, tmp_path):
        p = tmp_path / "audit.jsonl"
        p.write_text('{"event": "rag_query"}\nNOT JSON\n{"event": "x"}\n', encoding="utf-8")
        events = load_events(str(p))
        assert len(events) == 2
        assert events[0]["event"] == "rag_query"


class TestPrintMetrics:
    def test_no_events_message(self, tmp_path, capsys):
        audit_file = _write_audit(tmp_path, [])
        config_path = _write_config(tmp_path, audit_file)
        print_metrics(config_path)
        assert "No audit events found." in capsys.readouterr().out

    def test_mcp_and_graph_modes_both_counted(self, tmp_path, capsys):
        """Regression: mcp_rag_query stores the mode under 'mode', not
        'retrieval_mode'. Both must be counted, and neither shows as 'unknown'."""
        events = [
            # graph audit path → "retrieval_mode"
            {"event": "rag_query", "top_score": 0.40, "retrieval_mode": "hybrid"},
            {"event": "rag_query", "top_score": 0.20, "retrieval_mode": "semantic"},
            # MCP path → "mode"
            {"event": "mcp_rag_query", "top_score": 0.50, "mode": "hybrid"},
            {"event": "mcp_rag_query", "top_score": 0.10, "mode": "keyword"},
        ]
        audit_file = _write_audit(tmp_path, events)
        config_path = _write_config(tmp_path, audit_file)
        print_metrics(config_path)
        out = capsys.readouterr().out

        # hybrid appears in both a graph and an MCP event → 2
        assert "hybrid: 2" in out
        assert "semantic: 1" in out
        assert "keyword: 1" in out
        # The MCP events must NOT fall through to the "unknown" bucket.
        assert "unknown" not in out

    def test_score_stats_span_both_event_types(self, tmp_path, capsys):
        events = [
            {"event": "rag_query", "top_score": 0.40, "retrieval_mode": "hybrid"},
            {"event": "mcp_rag_query", "top_score": 0.60, "mode": "hybrid"},
        ]
        audit_file = _write_audit(tmp_path, events)
        config_path = _write_config(tmp_path, audit_file)
        print_metrics(config_path)
        out = capsys.readouterr().out
        # avg (0.5), min (0.4), max (0.6) computed across both event shapes.
        assert "avg: 0.500" in out
        assert "min: 0.400" in out
        assert "max: 0.600" in out


class TestMain:
    """Cover the ``cyclaw-metrics`` console entry point (``metrics:main``).

    Regression guard: the declared ``cyclaw-metrics = "metrics:main"`` script
    once raised ``AttributeError`` at invocation because the module defined only
    ``print_metrics`` and no ``main``. These tests fail loudly if the entry
    point is removed or stops delegating to ``print_metrics``.
    """

    def test_main_delegates_to_print_metrics(self, monkeypatch):
        calls: list[tuple] = []
        monkeypatch.setattr(metrics, "print_metrics", lambda *a, **k: calls.append((a, k)))
        assert metrics.main() is None
        assert len(calls) == 1

    def test_main_runs_end_to_end_with_default_config(self, tmp_path, monkeypatch, capsys):
        """``main()`` takes no args and reads ``config.yaml`` from the CWD;
        run it for real against a temp corpus to prove the wiring holds."""
        audit_file = _write_audit(
            tmp_path, [{"event": "rag_query", "top_score": 0.42, "retrieval_mode": "hybrid"}]
        )
        with open(tmp_path / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"logging": {"audit_file": audit_file}}, f)
        monkeypatch.chdir(tmp_path)
        metrics.main()
        out = capsys.readouterr().out
        assert "Total events: 1" in out
        assert "hybrid: 1" in out
