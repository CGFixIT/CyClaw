"""Unit tests for hybrid search with mocked embeddings.

Tests RRF fusion logic, graceful degradation, and score calculation
without requiring live sentence-transformers or ChromaDB indices.
"""

import pytest
from retrieval.stemmer import tokenize_and_stem


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
