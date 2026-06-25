"""Structural integrity tests for tests/conftest.py.

conftest.py is the shared test infrastructure for the entire CyClaw suite
(test_gate.py, test_graph.py, test_personality.py, ...). If any of the
fixtures or constants below drift away from the contract their consumers
expect, every other test file fails at collection time with confusing
errors.

This file asserts those contracts directly, in isolation, so the failure
points right at the broken fixture instead of at downstream tests.
Failures here are P0 blockers.

Run with:

    pytest tests/test_conftest_fixtures.py -v
"""

import pytest

from retrieval.hybrid_search import SearchResult
from tests.conftest import (
    MOCK_EMPTY_RESULTS,
    MOCK_HIGH_SCORE_RESULTS,
    MOCK_LOW_SCORE_RESULTS,
    TEST_CONFIG,
    MockGrokClient,
    MockLocalLLM,
    MockRetriever,
)


# ---------------------------------------------------------------------------
# 1. MockRetriever.hybrid_search
# ---------------------------------------------------------------------------

def test_mock_retriever_hybrid_search_returns_results():
    """hybrid_search returns the exact list of results it was constructed with."""
    mr = MockRetriever(MOCK_HIGH_SCORE_RESULTS)
    assert mr.hybrid_search("test query") == MOCK_HIGH_SCORE_RESULTS
    assert len(mr.hybrid_search("anything")) == len(MOCK_HIGH_SCORE_RESULTS)


# ---------------------------------------------------------------------------
# 2. MockRetriever.semantic_search / keyword_search
# ---------------------------------------------------------------------------

def test_mock_retriever_semantic_and_keyword_search():
    """All three search methods return the injected results list."""
    mr = MockRetriever(MOCK_HIGH_SCORE_RESULTS)
    assert mr.semantic_search("q", 5) == MOCK_HIGH_SCORE_RESULTS
    assert mr.keyword_search("q", 5) == MOCK_HIGH_SCORE_RESULTS


# ---------------------------------------------------------------------------
# 3. MockRetriever with empty results
# ---------------------------------------------------------------------------

def test_mock_retriever_empty_results():
    """Empty results must be returned as [] — never None."""
    mr = MockRetriever(MOCK_EMPTY_RESULTS)
    assert mr.hybrid_search("q") == []
    assert mr.hybrid_search("q") is not None


# ---------------------------------------------------------------------------
# 4. MockLocalLLM records last_prompt
# ---------------------------------------------------------------------------

def test_mock_local_llm_records_last_prompt():
    """generate() must store the prompt verbatim and return the canned response."""
    llm = MockLocalLLM("hello response")
    result = llm.generate("my test prompt")
    assert llm.last_prompt == "my test prompt"
    assert result == "hello response"


# ---------------------------------------------------------------------------
# 5. MockLocalLLM updates last_prompt on every call
# ---------------------------------------------------------------------------

def test_mock_local_llm_updates_last_prompt_on_second_call():
    """The most recent prompt overwrites the previous one (not appended)."""
    llm = MockLocalLLM("resp")
    llm.generate("first prompt")
    llm.generate("second prompt")
    assert llm.last_prompt == "second prompt"


# ---------------------------------------------------------------------------
# 6. MockGrokClient
# ---------------------------------------------------------------------------

def test_mock_grok_client_returns_response():
    """generate() returns the canned Grok response for any input."""
    grok = MockGrokClient("grok answer")
    assert grok.generate("any prompt") == "grok answer"


# ---------------------------------------------------------------------------
# 7. High-score results above retrieval threshold
# ---------------------------------------------------------------------------

def test_high_score_results_above_threshold():
    """MOCK_HIGH_SCORE_RESULTS[0] must clear retrieval.min_score in TEST_CONFIG."""
    min_score = TEST_CONFIG["retrieval"]["min_score"]
    assert len(MOCK_HIGH_SCORE_RESULTS) >= 1
    assert MOCK_HIGH_SCORE_RESULTS[0].score >= min_score, (
        f"high-score top result {MOCK_HIGH_SCORE_RESULTS[0].score} "
        f"is below threshold {min_score}"
    )


# ---------------------------------------------------------------------------
# 8. Low-score results below retrieval threshold
# ---------------------------------------------------------------------------

def test_low_score_results_below_threshold():
    """MOCK_LOW_SCORE_RESULTS[0] must NOT clear retrieval.min_score."""
    min_score = TEST_CONFIG["retrieval"]["min_score"]
    assert len(MOCK_LOW_SCORE_RESULTS) >= 1
    assert MOCK_LOW_SCORE_RESULTS[0].score < min_score, (
        f"low-score top result {MOCK_LOW_SCORE_RESULTS[0].score} "
        f"is above threshold {min_score}"
    )


# ---------------------------------------------------------------------------
# 9. TEST_CONFIG has required keys with the right types
# ---------------------------------------------------------------------------

def test_test_config_has_required_keys():
    """TEST_CONFIG must expose the key paths consumed by gateway + graph tests."""
    assert isinstance(TEST_CONFIG["retrieval"]["min_score"], float)
    assert isinstance(TEST_CONFIG["app"]["mode"], str)
    assert isinstance(TEST_CONFIG["personality"]["enabled"], bool)
    assert isinstance(TEST_CONFIG["models"]["grok"]["enabled"], bool)
    assert isinstance(
        TEST_CONFIG["policy"]["fallback"]["send_local_context_to_grok"], bool
    )
    assert isinstance(TEST_CONFIG["security"]["allowed_origins"], list)


# ---------------------------------------------------------------------------
# 10. SearchResult fields populated on every high-score mock
# ---------------------------------------------------------------------------

def test_search_result_fields_populated():
    """Every MOCK_HIGH_SCORE_RESULTS entry must have all six core fields set.

    SearchResult.chunk_id is an int (not str), so we assert the type and
    non-None instead of comparing to the empty string.
    """
    assert len(MOCK_HIGH_SCORE_RESULTS) >= 1
    for sr in MOCK_HIGH_SCORE_RESULTS:
        assert isinstance(sr, SearchResult)
        assert sr.text is not None and sr.text != ""
        assert sr.score is not None and isinstance(sr.score, float)
        assert sr.source is not None and sr.source != ""
        assert sr.chunk_id is not None and isinstance(sr.chunk_id, int)
        assert sr.stem_tags is not None and isinstance(sr.stem_tags, list)
        assert sr.retrieval_mode is not None and sr.retrieval_mode != ""


# ---------------------------------------------------------------------------
# 11. test_config fixture is isolated from the module-level TEST_CONFIG
# ---------------------------------------------------------------------------

def test_test_config_fixture_is_isolated_from_module_global(test_config):
    """Mutating a deeply-nested value in the per-test config must NOT leak.

    The fixture used to ``TEST_CONFIG.copy()`` (shallow) and only hand-clone
    ``indexing`` / ``logging``. Every other nested dict was a shared reference
    to the module global, so a test toggling ``grok.enabled`` or appending to
    ``banned_patterns`` silently poisoned every later test that used the fixture.
    deepcopy must make each fixture instance fully independent.
    """
    cfg, _ = test_config
    grok_before = TEST_CONFIG["models"]["grok"]["enabled"]
    patterns_before = list(TEST_CONFIG["policy"]["prompt_filter"]["banned_patterns"])

    # Mutate nested dicts that the OLD shallow copy left shared with the global.
    cfg["models"]["grok"]["enabled"] = not grok_before
    cfg["policy"]["prompt_filter"]["banned_patterns"].append("LEAKED_FROM_TEST")
    cfg["retrieval"]["min_score"] = 0.999

    # The module-level constant must be untouched.
    assert TEST_CONFIG["models"]["grok"]["enabled"] == grok_before
    assert TEST_CONFIG["policy"]["prompt_filter"]["banned_patterns"] == patterns_before
    assert "LEAKED_FROM_TEST" not in TEST_CONFIG["policy"]["prompt_filter"]["banned_patterns"]


def test_two_config_fixtures_do_not_share_nested_state(test_config, tmp_path):
    """Two independent reads of the fixture-built config must not alias nested dicts."""
    cfg1, _ = test_config
    # Build a second config the same way the fixture does, to confirm the source
    # constant is never the shared object handed out.
    import copy as _copy

    cfg2 = _copy.deepcopy(TEST_CONFIG)
    cfg1["models"]["grok"]["enabled"] = True
    assert cfg2["models"]["grok"]["enabled"] is False
    assert cfg1["models"] is not cfg2["models"]
