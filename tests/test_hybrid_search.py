"""Unit tests for hybrid search with mocked embeddings.

Tests RRF fusion logic, graceful degradation, and score calculation
without requiring live sentence-transformers or ChromaDB indices.
"""

import json

import pytest
import yaml
from unittest.mock import MagicMock, patch

from retrieval.stemmer import tokenize_and_stem
from tests.conftest import TEST_CONFIG


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


class TestSinglePathRRFScaling:
    """PR #99 #6: when only one retrieval path returns, the gating score must be
    on the RRF scale (1/(rrf_k+rank)) — not the raw BM25/semantic score — so the
    min_score gate (tuned for RRF) behaves correctly under degraded retrieval."""

    def _build_retriever(self, tmp_path):
        chunks = ["veeam immutability backup", "chromadb vector store", "bm25 keyword search"]
        tokenized = [c.split() for c in chunks]
        metadata = [{"source": f"d{i}.md", "chunk_id": i, "stem_tags": "[]"} for i in range(len(chunks))]
        bm25_path = tmp_path / "bm25.json"
        with open(bm25_path, "w") as f:
            json.dump({"tokenized_corpus": tokenized, "chunks": chunks, "metadata": metadata}, f)

        cfg = TEST_CONFIG.copy()
        cfg["indexing"] = {**cfg["indexing"], "bm25_path": str(bm25_path),
                           "chroma_path": str(tmp_path / "chroma_db")}
        (tmp_path / "chroma_db").mkdir()
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(cfg, f)

        with patch("retrieval.hybrid_search.chromadb.PersistentClient") as mock_client:
            mock_client.return_value.get_collection.return_value = MagicMock()
            from retrieval.hybrid_search import HybridRetriever
            return HybridRetriever(config_path=str(config_file))

    def test_keyword_only_uses_rrf_scale(self, tmp_path):
        r = self._build_retriever(tmp_path)
        with patch.object(r, "semantic_search", return_value=[]):  # force keyword-only
            results = r.hybrid_search("veeam immutability")

        assert results, "keyword path should return hits"
        top = results[0]
        # gating score is RRF-scaled (rank 0 => 1/(rrf_k+0)), NOT the raw BM25 score
        assert abs(top.score - 1 / (r.rrf_k + 0)) < 1e-9
        assert abs(top.rrf_score - 1 / (r.rrf_k + 0)) < 1e-9
        # raw BM25 score preserved for provenance
        assert top.keyword_score is not None and top.keyword_score > 0
        assert top.score != top.keyword_score
        # degraded single-path result gates below the shipped min_score (0.028)
        assert top.score < 0.028
