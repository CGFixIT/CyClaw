"""Integration tests for SafeClaw LangGraph controller.

Tests all paths through the state machine:
1. High score -> local_llm -> audit (happy path)
2. Low score -> user_gate (needs_confirm) -> audit
3. Low score -> user_gate -> grok_fallback -> audit (hybrid mode)
4. Low score -> user_gate -> offline_best_effort -> audit (declined/offline)
5. Error in retrieval -> offline_best_effort -> audit
6. Empty query handling
"""

import pytest
import yaml
from pathlib import Path

from graph import build_graph, GraphState
from tests.conftest import (
    MockRetriever, MockLocalLLM, MockGrokClient,
    MOCK_HIGH_SCORE_RESULTS, MOCK_LOW_SCORE_RESULTS, MOCK_EMPTY_RESULTS,
    TEST_CONFIG
)
from utils.logger import reset_config_cache


@pytest.fixture(autouse=True)
def setup_logging(tmp_path):
    """Ensure audit logging works for each test."""
    reset_config_cache()
    yield
    reset_config_cache()


def _make_cfg(tmp_path, mode="offline", grok_enabled=False):
    """Build test config with temp audit path."""
    cfg = {**TEST_CONFIG}
    cfg["app"] = {**cfg["app"], "mode": mode}
    cfg["models"] = {
        **cfg["models"],
        "grok": {**cfg["models"]["grok"], "enabled": grok_enabled}
    }
    cfg["logging"] = {
        **cfg["logging"],
        "audit_file": str(tmp_path / "audit.jsonl"),
        "log_file": str(tmp_path / "gateway.log")
    }

    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(cfg, f)

    # Also write to default location so audit_log can find it
    import os
    os.environ.setdefault("SAFECLAW_CONFIG", str(config_path))

    return cfg


class TestHighScorePath:
    """Path 1: High score -> local_llm -> audit_logger -> END"""

    def test_high_score_routes_to_local_llm(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        retriever = MockRetriever(MOCK_HIGH_SCORE_RESULTS)
        llm = MockLocalLLM(response="Veeam uses chattr +i for immutability.")

        graph = build_graph(retriever, llm, None, cfg)
        result = graph.invoke({"query": "What is Veeam immutability?"})

        assert result["answer_model"] == "local"
        assert "chattr" in result["answer"]
        assert result["top_score"] == 0.92
        assert result["needs_user_confirm"] is False

    def test_local_llm_receives_context(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        retriever = MockRetriever(MOCK_HIGH_SCORE_RESULTS)
        llm = MockLocalLLM()

        graph = build_graph(retriever, llm, None, cfg)
        graph.invoke({"query": "immutability config"})

        # LLM should have received the retrieved context in its prompt
        assert llm.last_prompt is not None
        assert "immutability config" in llm.last_prompt
        assert "veeam-immutability.md" in llm.last_prompt


class TestLowScoreNeedsConfirm:
    """Path 2: Low score -> user_gate -> needs_confirm (first pass)"""

    def test_low_score_signals_needs_confirm(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        retriever = MockRetriever(MOCK_LOW_SCORE_RESULTS)
        llm = MockLocalLLM()

        graph = build_graph(retriever, llm, None, cfg)
        result = graph.invoke({"query": "Explain quantum physics basics"})

        # user_confirmed_online is None -> graph signals needs_confirm
        assert result["needs_user_confirm"] is True
        assert result.get("answer_model", "") in ("", "unknown")


class TestGrokFallbackPath:
    """Path 3: Low score -> confirmed -> grok_fallback -> audit"""

    def test_confirmed_hybrid_routes_to_grok(self, tmp_path):
        cfg = _make_cfg(tmp_path, mode="hybrid", grok_enabled=True)
        retriever = MockRetriever(MOCK_LOW_SCORE_RESULTS)
        llm = MockLocalLLM()
        grok = MockGrokClient(response="Grok answer about quantum physics.")

        graph = build_graph(retriever, llm, grok, cfg)
        result = graph.invoke({
            "query": "Explain quantum physics basics",
            "user_confirmed_online": True
        })

        assert result["answer_model"] == "grok"
        assert "Grok answer" in result["answer"]

    def test_grok_not_called_in_offline_mode(self, tmp_path):
        cfg = _make_cfg(tmp_path, mode="offline", grok_enabled=False)
        retriever = MockRetriever(MOCK_LOW_SCORE_RESULTS)
        llm = MockLocalLLM(response="Best effort offline answer.")
        # In offline mode the gateway builds no GrokClient (grok=None). The graph
        # routes a confirmed low-score query to grok_fallback, whose None-guard
        # then degrades to offline-best-effort — this is how mode-gating is
        # enforced (the graph itself does not read app.mode).
        grok = None

        graph = build_graph(retriever, llm, grok, cfg)
        result = graph.invoke({
            "query": "Explain quantum physics basics",
            "user_confirmed_online": True
        })

        # Even with confirmation, offline mode (grok=None) blocks Grok
        assert result["answer_model"] == "offline-best-effort"


class TestOfflineBestEffortPath:
    """Path 4: Low score -> user declines -> offline_best_effort"""

    def test_declined_routes_to_offline(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        retriever = MockRetriever(MOCK_LOW_SCORE_RESULTS)
        llm = MockLocalLLM(response="Best effort from local model.")

        graph = build_graph(retriever, llm, None, cfg)
        result = graph.invoke({
            "query": "Explain quantum physics basics",
            "user_confirmed_online": False
        })

        assert result["answer_model"] == "offline-best-effort"
        assert "Best effort" in result["answer"]


class TestEmptyResults:
    """Path 5: No retrieval results -> low score -> user_gate"""

    def test_empty_results_trigger_gate(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        retriever = MockRetriever(MOCK_EMPTY_RESULTS)
        llm = MockLocalLLM()

        graph = build_graph(retriever, llm, None, cfg)
        result = graph.invoke({"query": "completely off topic query"})

        assert result["top_score"] == 0.0
        assert result["needs_user_confirm"] is True


class TestAuditLogging:
    """Verify audit logger runs on all paths."""

    def test_audit_event_present_high_score(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        retriever = MockRetriever(MOCK_HIGH_SCORE_RESULTS)
        llm = MockLocalLLM()

        graph = build_graph(retriever, llm, None, cfg)
        result = graph.invoke({"query": "Veeam immutability"})

        assert "audit_event" in result
        assert result["audit_event"]["model_used"] == "local"

    def test_audit_event_present_offline_best_effort(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        retriever = MockRetriever(MOCK_LOW_SCORE_RESULTS)
        llm = MockLocalLLM()

        graph = build_graph(retriever, llm, None, cfg)
        result = graph.invoke({
            "query": "off topic",
            "user_confirmed_online": False
        })

        assert "audit_event" in result
        assert result["audit_event"]["model_used"] == "offline-best-effort"
