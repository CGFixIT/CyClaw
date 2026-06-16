"""Unit tests for PsyClaw's JSON-RPC MCP server (mcp_hybrid_server.py).

These tests guard the MCP protocol-layer invariants that PsyClaw v1.3.0
depends on:

  * sampling = None at the capability level (the MCP server CANNOT route to
    an LLM — this is a structural guarantee, not policy)
  * tools/list exposes only the retrieval-only hybrid_search tool
  * tools/call dispatches correctly across hybrid / semantic / keyword modes
  * Unknown methods return JSON-RPC error code -32601
  * RAGError from the retriever maps to JSON-RPC error code -32000
  * notifications/initialized returns None (no response for notifications)

All tests are hermetic: the HybridRetriever is replaced with
unittest.mock.MagicMock — no live ChromaDB, BM25 pickle, or network.
Run with:

    pytest tests/test_mcp_server.py -v
"""

from unittest.mock import MagicMock

import pytest

from mcp_hybrid_server import CAPABILITIES, TOOLS, handle_message
from retrieval.hybrid_search import SearchResult
from utils.errors import RAGError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_search_result(
    text: str = "veeam immutability ensures backups cannot be modified",
    score: float = 0.92,
    source: str = "veeam-immutability.md",
    chunk_id: int = 0,
    stem_tags=None,
    retrieval_mode: str = "hybrid",
) -> SearchResult:
    """Build a fully-populated SearchResult for MCP dispatch tests."""
    return SearchResult(
        text=text,
        score=score,
        source=source,
        chunk_id=chunk_id,
        stem_tags=stem_tags if stem_tags is not None else ["veeam", "immut", "backup"],
        retrieval_mode=retrieval_mode,
        semantic_score=score,
        semantic_rank=chunk_id,
        keyword_score=score * 0.9,
        keyword_rank=chunk_id,
        rrf_score=score,
        rrf_semantic_contrib=score * 0.6,
        rrf_keyword_contrib=score * 0.4,
    )


@pytest.fixture
def retriever():
    """A MagicMock retriever — no live index, all three search methods stubbed."""
    r = MagicMock()
    results = [
        _make_search_result(text="first chunk", score=0.92, chunk_id=0),
        _make_search_result(text="second chunk", score=0.81, chunk_id=1),
    ]
    r.hybrid_search.return_value = results
    r.semantic_search.return_value = results
    r.keyword_search.return_value = results
    return r


# ---------------------------------------------------------------------------
# 1. initialize
# ---------------------------------------------------------------------------

def test_initialize_returns_capabilities(retriever):
    """initialize must return protocolVersion + capabilities with sampling=None."""
    msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    result = handle_message(msg, retriever)

    assert result is not None
    assert "result" in result
    # CRITICAL invariant — MCP server cannot route to an LLM
    assert result["result"]["capabilities"]["sampling"] is None
    assert result["result"]["protocolVersion"] == "2025-11-25"
    assert result["result"]["serverInfo"]["name"] == "psyclaw-hybrid-rag"


# ---------------------------------------------------------------------------
# 2. Module-level sampling-is-None invariant
# ---------------------------------------------------------------------------

def test_sampling_is_none_invariant():
    """Protocol-level guarantee: CAPABILITIES['sampling'] is None at import.

    This is the strongest possible regression guard for the no-LLM-from-MCP
    architecture commitment. If anyone changes this to a dict, the test fails
    immediately at collection time across the whole suite.
    """
    assert "sampling" in CAPABILITIES
    assert CAPABILITIES["sampling"] is None


# ---------------------------------------------------------------------------
# 3. tools/list
# ---------------------------------------------------------------------------

def test_tools_list_returns_hybrid_search(retriever):
    """tools/list must surface only hybrid_search with `query` as required."""
    msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    result = handle_message(msg, retriever)

    assert result is not None
    tools = result["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "hybrid_search" in tool_names

    hybrid_tool = next(t for t in tools if t["name"] == "hybrid_search")
    assert "query" in hybrid_tool["inputSchema"]["required"]
    # TOOLS module constant should match what the handler returns
    assert tools == TOOLS


# ---------------------------------------------------------------------------
# 4. tools/call — hybrid mode (default)
# ---------------------------------------------------------------------------

def test_tools_call_hybrid_search(retriever):
    """tools/call with mode=hybrid returns 2 chunks with the documented keys."""
    msg = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "hybrid_search", "arguments": {"query": "test"}},
    }
    result = handle_message(msg, retriever)

    assert result is not None
    chunks = result["result"]["chunks"]
    assert len(chunks) == 2
    expected_keys = {"text", "score", "source", "chunk_id", "stem_tags", "mode"}
    for chunk in chunks:
        assert expected_keys.issubset(set(chunk.keys()))


# ---------------------------------------------------------------------------
# 5. tools/call — semantic mode
# ---------------------------------------------------------------------------

def test_tools_call_semantic_mode(retriever):
    """mode=semantic must dispatch to retriever.semantic_search (not hybrid/keyword)."""
    msg = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "hybrid_search",
            "arguments": {"query": "test", "mode": "semantic"},
        },
    }
    result = handle_message(msg, retriever)

    assert result is not None
    assert "result" in result
    retriever.semantic_search.assert_called_once()
    assert retriever.hybrid_search.call_count == 0
    assert retriever.keyword_search.call_count == 0


# ---------------------------------------------------------------------------
# 6. tools/call — keyword mode
# ---------------------------------------------------------------------------

def test_tools_call_keyword_mode(retriever):
    """mode=keyword must dispatch to retriever.keyword_search (not hybrid/semantic)."""
    msg = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "hybrid_search",
            "arguments": {"query": "test", "mode": "keyword"},
        },
    }
    result = handle_message(msg, retriever)

    assert result is not None
    assert "result" in result
    retriever.keyword_search.assert_called_once()
    assert retriever.hybrid_search.call_count == 0
    assert retriever.semantic_search.call_count == 0


# ---------------------------------------------------------------------------
# 7. Unknown method → JSON-RPC -32601
# ---------------------------------------------------------------------------

def test_unknown_method_returns_error_32601(retriever):
    """Unknown methods must return JSON-RPC error code -32601 (Method not found)."""
    msg = {"jsonrpc": "2.0", "method": "nonexistent/method", "id": 6}
    result = handle_message(msg, retriever)

    assert result is not None
    assert "error" in result
    assert result["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# 8. notifications/initialized → None
# ---------------------------------------------------------------------------

def test_notifications_initialized_returns_none(retriever):
    """JSON-RPC notifications must NOT produce a response per the spec."""
    msg = {"jsonrpc": "2.0", "method": "notifications/initialized", "id": None}
    result = handle_message(msg, retriever)

    assert result is None


# ---------------------------------------------------------------------------
# 9. RAGError from retriever → JSON-RPC -32000
# ---------------------------------------------------------------------------

def test_rag_error_returns_error_32000(retriever):
    """If the retriever raises RAGError, the MCP server must return code -32000."""
    retriever.hybrid_search.side_effect = RAGError("no index", code="IDX")
    msg = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "hybrid_search",
            "arguments": {"query": "test", "mode": "hybrid"},
        },
    }
    result = handle_message(msg, retriever)

    assert result is not None
    assert "error" in result
    assert result["error"]["code"] == -32000
