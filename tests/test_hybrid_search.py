"""Unit tests for hybrid search with mocked embeddings.

Tests RRF fusion logic, graceful degradation, and score calculation
without requiring live sentence-transformers or ChromaDB indices.
"""

import pytest
from types import SimpleNamespace

from retrieval.stemmer import tokenize_and_stem
from retrieval.hybrid_search import HybridRetriever, SearchResult
from retrieval.vector_store import parse_stem_tags


class TestRRFFusion:
    """Test Reciprocal Rank Fusion math independently."""

    def test_rrf_score_calculation(self):
        """Verify RRF formula: 1 / (k + rank)"""
        k = 60
        # Rank 0 (best): 1/60 = 0.01667
        # Rank 1: 1/61 = 0.01639
        assert abs(1 / (k + 0) - 0.01667) < 0.001
        assert abs(1 / (k + 1) - 0.01639) < 0.001

    def test_combined_rrf_scores_higher(self):
        """Document appearing in both semantic and keyword gets higher score."""
        k = 60
        semantic_only = 1 / (k + 0)  # 0.01667
        combined = 1 / (k + 0) + 1 / (k + 2)  # 0.01667 + 0.01613 = 0.0328
        assert combined > semantic_only

    def test_rrf_ordering(self):
        """Higher combined rank should yield higher score."""
        k = 60
        score_rank_0_0 = 1 / (k + 0) + 1 / (k + 0)  # Best in both
        score_rank_0_3 = 1 / (k + 0) + 1 / (k + 3)  # Best in one, 4th in other
        score_rank_2_2 = 1 / (k + 2) + 1 / (k + 2)  # 3rd in both
        assert score_rank_0_0 > score_rank_0_3
        assert score_rank_0_3 > score_rank_2_2


class TestSinglePathNormalization:
    """Single-path fallback scores must be re-based into the RRF range so the
    min_score gate (calibrated for fused 1/(k+rank) output) stays meaningful."""

    @staticmethod
    def _kw_hit(score, chunk_id):
        return SearchResult(
            text="t", score=score, source="s.md", chunk_id=chunk_id,
            stem_tags=[], retrieval_mode="keyword",
            keyword_score=score, keyword_rank=chunk_id,
        )

    def test_raw_bm25_scores_rebased_to_rrf(self):
        fake = SimpleNamespace(rrf_k=60)
        # Raw BM25 scores (unbounded) — 2.7 would trivially clear min_score=0.028
        hits = [self._kw_hit(2.7, 0), self._kw_hit(0.01, 1)]
        out = HybridRetriever._normalize_single_path(fake, hits)

        assert out[0].score == pytest.approx(1 / 60)
        assert out[1].score == pytest.approx(1 / 61)
        # rrf_score mirrors score; keyword contrib is populated for a keyword path
        assert out[0].rrf_score == pytest.approx(1 / 60)
        assert out[0].rrf_keyword_contrib == pytest.approx(1 / 60)
        # Ordering preserved (rank 0 outranks rank 1)
        assert out[0].score > out[1].score

    def test_single_path_top_below_fusion_agreement(self):
        """A single-path top hit (one RRF term) must score below two agreeing
        paths (two terms) — degraded retrieval is lower confidence."""
        fake = SimpleNamespace(rrf_k=60)
        out = HybridRetriever._normalize_single_path(fake, [self._kw_hit(9.9, 0)])
        single = out[0].score
        both_paths_agree = 1 / 60 + 1 / 60
        assert single < both_paths_agree


class TestFusionReturnsFullUnion:
    """The fuser must return the entire RRF-fused union and let each caller
    slice to its own budget. A previous inner cap of
    ``max(top_k_semantic, top_k_keyword)`` silently dropped chunks an MCP caller
    requested via ``top_k > 5``."""

    @staticmethod
    def _hit(mode, chunk_id):
        return SearchResult(
            text=f"t{chunk_id}", score=1.0, source="s.md", chunk_id=chunk_id,
            stem_tags=[], retrieval_mode=mode,
        )

    def test_disjoint_paths_are_not_truncated(self):
        # 5 semantic + 5 keyword chunks with NO overlap -> a 10-chunk union.
        sem = [self._hit("semantic", i) for i in range(5)]
        kw = [self._hit("keyword", i) for i in range(5, 10)]
        fake = SimpleNamespace(
            rrf_k=60, top_k_semantic=5, top_k_keyword=5,
            semantic_search=lambda q: sem,
            keyword_search=lambda q: kw,
        )
        out = HybridRetriever.hybrid_search(fake, "q")
        # Pre-fix this returned only 5 (max(5, 5)); the other 5 were dropped.
        assert len(out) == 10
        assert {r.chunk_id for r in out} == set(range(10))


class TestTokenizationForBM25:
    """Ensure tokenization produces useful BM25 input."""

    def test_veeam_terms(self):
        tokens = tokenize_and_stem("Veeam immutability backup configuration")
        assert "veeam" in tokens
        assert "immut" in tokens or "immutab" in tokens
        assert "backup" in tokens

    def test_technical_query(self):
        tokens = tokenize_and_stem("How do I configure SOBR with S3?")
        assert "configur" in tokens or "configure" in tokens
        assert "sobr" in tokens

    def test_empty_query(self):
        tokens = tokenize_and_stem("")
        assert tokens == []

    def test_single_word(self):
        tokens = tokenize_and_stem("kubernetes")
        assert len(tokens) == 1
        # `kubernetes` is intentionally folded to the domain token `k8s`
        # (retrieval/stemmer.py _CUSTOM_STEMS), not Porter-stemmed.
        assert tokens[0] == "k8s"


class TestParseStemTags:
    """parse_stem_tags must never crash on corrupted metadata."""

    def test_valid_json_string(self):
        assert parse_stem_tags('["veeam", "backup"]') == ["veeam", "backup"]

    def test_already_list(self):
        assert parse_stem_tags(["already", "parsed"]) == ["already", "parsed"]

    def test_empty_json_array(self):
        assert parse_stem_tags("[]") == []

    def test_malformed_json_returns_empty(self):
        assert parse_stem_tags("{truncated") == []

    def test_none_returns_empty(self):
        assert parse_stem_tags(None) == []

    def test_non_list_json_returns_empty(self):
        assert parse_stem_tags('"just a string"') == []

    def test_empty_string_returns_empty(self):
        assert parse_stem_tags("") == []
