"""Real ChromaDB + BM25 RAG integration test for CI.

Validates the retrieval stack end-to-end without LLM:
- RRF fusion correctness (ChromaDB semantic + BM25 keyword)
- min_score gate enforcement
- Index build and query flow
- Parametrized queries for coverage

Previously defined as a script (run_integration_test()) outside pytest collection;
now a proper pytest test_rag_integration_full_stack() for automated CI runs.
"""

from pathlib import Path

import yaml

from retrieval.indexer import build_index
from retrieval.hybrid_search import HybridRetriever


INTEGRATION_QUERIES = [
    ("What fusion method does CyClaw use to blend semantic and keyword results?", "cyclaw_overview"),
    ("What is the primary retrieval strategy of CyClaw?", "cyclaw_overview"),
]


def test_rag_integration_full_stack() -> None:
    """Full integration test: index build → hybrid search → min_score gate."""
    config_path = Path("config.yaml")
    assert config_path.exists(), "config.yaml not found"

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    min_score = float(cfg["retrieval"]["min_score"])
    corpus_path = Path(cfg["corpus"]["path"])

    # Build index from fresh corpus
    assert corpus_path.exists(), f"Corpus path not found: {corpus_path}"
    build_index()

    retriever = HybridRetriever()
    assert retriever is not None, "Failed to instantiate HybridRetriever"

    # Validate each query clears the min_score gate
    for query, expected_source_substr in INTEGRATION_QUERIES:
        results = retriever.hybrid_search(query)
        assert results, f"No results for query: {query}"

        top = results[0]
        assert top.score >= min_score, (
            f"Top result ({top.score:.6f}) below min_score gate ({min_score}); "
            f"query={query}"
        )
        assert expected_source_substr in top.source, (
            f"Expected substring '{expected_source_substr}' not in source '{top.source}'"
        )
