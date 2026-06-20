#!/usr/bin/env python3
"""Real (non-mocked) offline RAG smoke test for CI.

Unlike the previous fully-mocked smoke (a hardcoded MockRetriever that returned a
constant dict), this exercises the *actual* retrieval stack end to end:

  1. Build a real ChromaDB (semantic) + BM25 (keyword) index from data/corpus
     via retrieval.indexer.build_index().
  2. Instantiate the real HybridRetriever and run a real hybrid_search() for a
     question that the committed corpus (data/corpus/cyclaw_overview.md) answers.
  3. Assert the retriever returns a hit whose fused score clears the configured
     retrieval.min_score gate — i.e. a genuine "vault hit", not a vault miss.

No LLM is involved: CI has no LM Studio, so this stops at retrieval (the part
that ChromaDB + BM25 actually own). Generation is covered separately by the
gate/graph unit tests with a mocked LLM.

Exit non-zero on any failure so the CI step goes red on a real retrieval regression.
"""

import sys

import yaml

from retrieval.indexer import build_index
from retrieval.hybrid_search import HybridRetriever

# A question answered by data/corpus/cyclaw_overview.md ("RRF Fusion ... blend
# semantic and keyword results"). Picked to land above the min_score gate.
QUERY = "What fusion method does CyClaw use to blend semantic and keyword results?"
EXPECTED_SOURCE_SUBSTR = "cyclaw_overview"


def main() -> int:
    print("=== Real Offline RAG Query Smoke (ChromaDB + BM25) ===")

    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    min_score = float(cfg["retrieval"]["min_score"])

    print("Building real index from", cfg["corpus"]["path"], "...")
    build_index()

    retriever = HybridRetriever()
    results = retriever.hybrid_search(QUERY)

    print("Query:        ", QUERY)
    print("Hits returned:", len(results))
    if not results:
        print("FAIL: retriever returned zero hits for a corpus-answerable query")
        return 1

    top = results[0]
    print("Top source:   ", top.source)
    print("Top score:    ", round(top.score, 6), "(min_score gate:", min_score, ")")
    print("Retrieval mode:", top.retrieval_mode)

    if top.score < min_score:
        print(f"FAIL: top score {top.score} below min_score gate {min_score} (vault miss)")
        return 1

    if EXPECTED_SOURCE_SUBSTR not in top.source:
        # Not fatal to retrieval correctness, but the smoke is meant to land on the
        # known corpus doc; surface it loudly so a corpus change is noticed.
        print(f"WARN: top source {top.source!r} did not contain {EXPECTED_SOURCE_SUBSTR!r}")

    print("Real RAG query passed (vault hit above gate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
