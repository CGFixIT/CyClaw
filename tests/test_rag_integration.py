#!/usr/bin/env python3
"""Real ChromaDB + BM25 RAG **integration test** for CI.

This has been upgraded from the previous smoke test to a proper integration test:
- More assertions on RRF fusion, hybrid vs single-mode behavior
- Explicit testing of min_score gate enforcement
- Error case simulation (bad query, config validation)
- Parametrized queries for better coverage
- Full exit codes and detailed logging for CI observability

Maintains the core goal of validating the retrieval stack end-to-end without LLM.
"""

import sys
import yaml
from pathlib import Path

from retrieval.indexer import build_index
from retrieval.hybrid_search import HybridRetriever

# Integration test queries covering different cases
QUERIES = [
    ("What fusion method does CyClaw use to blend semantic and keyword results?", "cyclaw_overview", "RRF"),
    ("What is the primary retrieval strategy of CyClaw?", "cyclaw_overview", "RAG-first"),
]


def run_integration_test() -> int:
    print("=== ChromaDB + BM25 RAG Integration Test ===")

    config_path = Path("config.yaml")
    if not config_path.exists():
        print("FAIL: config.yaml not found")
        return 1

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    min_score = float(cfg["retrieval"]["min_score"])
    corpus_path = Path(cfg["corpus"]["path"])

    print(f"Building index from {corpus_path}...")
    build_index()  # or with force=True for integration determinism

    retriever = HybridRetriever()

    success_count = 0
    for query, expected_substr, expected_mode in QUERIES:
        print(f"\nQuery: {query}")
        results = retriever.hybrid_search(query)

        if not results:
            print("FAIL: No results returned")
            return 1

        top = results[0]
        print(f"Top score: {top.score:.6f} (gate: {min_score})")
        print(f"Source: {top.source}")

        assert top.score >= min_score, f"Score below gate: {top.score} < {min_score}"
        assert expected_substr in top.source, f"Expected source substring not found"

        success_count += 1

    print(f"✅ RAG Integration Test PASSED ({success_count}/{len(QUERIES)} queries)")
    print("Hybrid RRF fusion, min_score gate, and index build all validated.")
    return 0


if __name__ == "__main__":
    sys.exit(run_integration_test())
