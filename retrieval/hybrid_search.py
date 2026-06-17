"""
Hybrid retrieval: semantic (ChromaDB) + keyword (BM25) with RRF fusion.

Uses sentence-transformers directly for query embeddings (no Ollama).
Degrades gracefully if one retrieval path fails.
"""

import heapq
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import chromadb
from chromadb.config import Settings
from rank_bm25 import BM25Okapi
import yaml

from .stemmer import tokenize_and_stem
from .embeddings import get_embedding
from utils.errors import IndexNotFoundError, EmbeddingServiceError
from utils.logger import audit_log

@dataclass
class SearchResult:
    """Single search result with provenance metadata."""
    text: str
    score: float
    source: str
    chunk_id: int
    stem_tags: List[str]
    retrieval_mode: str  # "semantic" | "keyword" | "hybrid"
    semantic_score: Optional[float] = None
    semantic_rank: Optional[int] = None
    keyword_score: Optional[float] = None
    keyword_rank: Optional[int] = None
    rrf_score: Optional[float] = None
    rrf_semantic_contrib: Optional[float] = None
    rrf_keyword_contrib: Optional[float] = None
    provenance: dict = field(default_factory=dict)

class HybridRetriever:
    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path) as f:
            self.cfg = yaml.safe_load(f)

        self.config_path = config_path
        chroma_path = self.cfg["indexing"]["chroma_path"]
        collection_name = self.cfg["indexing"]["collection_name"]
        bm25_path = self.cfg["indexing"]["bm25_path"]

        if not Path(chroma_path).exists():
            raise IndexNotFoundError(
                f"ChromaDB index not found at {chroma_path}. Run: python -m retrieval.indexer"
            )
        if not Path(bm25_path).exists():
            raise IndexNotFoundError(
                f"BM25 index not found at {bm25_path}. Run: python -m retrieval.indexer"
            )

        client = chromadb.PersistentClient(
            path=chroma_path,
            settings=Settings(anonymized_telemetry=False)
        )
        try:
            self.collection = client.get_collection(collection_name)
        except Exception as e:
            raise IndexNotFoundError(
                f"Collection '{collection_name}' not found in ChromaDB: {e}"
            )

        resolved = Path(bm25_path).resolve()
        if not resolved.is_file():
            raise IndexNotFoundError(f"BM25 index path is not a regular file: {bm25_path}")
        with open(resolved, "r", encoding="utf-8") as f:
            bm25_data = json.load(f)
            self.bm25 = BM25Okapi(bm25_data["tokenized_corpus"])
            self.bm25_chunks = bm25_data["chunks"]
            self.bm25_metadata = bm25_data["metadata"]

        self.top_k_semantic = self.cfg["retrieval"]["top_k_semantic"]
        self.top_k_keyword = self.cfg["retrieval"]["top_k_keyword"]
        self.rrf_k = self.cfg["retrieval"]["rrf_k"]

    def semantic_search(self, query: str, k: Optional[int] = None) -> List[SearchResult]:
        if k is None:
            k = self.top_k_semantic
        emb = get_embedding(query, self.config_path)
        results = self.collection.query(query_embeddings=[emb], n_results=k)
        hits = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                score = 1 - results["distances"][0][i]
                meta = results["metadatas"][0][i]
                stem_raw = meta.get("stem_tags", "[]")
                stem_tags = json.loads(stem_raw) if isinstance(stem_raw, str) else stem_raw
                hits.append(SearchResult(
                    text=doc, score=score, source=meta["source"],
                    chunk_id=meta["chunk_id"], stem_tags=stem_tags,
                    retrieval_mode="semantic", semantic_score=score, semantic_rank=i,
                    provenance={"semantic": {"rank": i, "score": score}}
                ))
        return hits

    def keyword_search(self, query: str, k: Optional[int] = None) -> List[SearchResult]:
        if k is None:
            k = self.top_k_keyword
        query_tokens = tokenize_and_stem(query)
        scores = self.bm25.get_scores(query_tokens)
        # Top-k selection only: heapq.nlargest is O(n log k) and matches the
        # ordering of sorted(..., reverse=True)[:k], avoiding a full O(n log n)
        # sort of every chunk in the corpus on each keyword query.
        top_indices = heapq.nlargest(k, range(len(scores)), key=scores.__getitem__)
        hits = []
        for idx in top_indices:
            if scores[idx] > 0:
                meta = self.bm25_metadata[idx]
                stem_raw = meta.get("stem_tags", "[]")
                stem_tags = json.loads(stem_raw) if isinstance(stem_raw, str) else stem_raw
                hits.append(SearchResult(
                    text=self.bm25_chunks[idx], score=scores[idx],
                    source=meta["source"], chunk_id=meta["chunk_id"],
                    stem_tags=stem_tags, retrieval_mode="keyword",
                    keyword_score=scores[idx], keyword_rank=len(hits),
                    provenance={"keyword": {"rank": len(hits), "score": scores[idx]}}
                ))
        return hits

    def hybrid_search(self, query: str) -> List[SearchResult]:
        semantic_hits: List[SearchResult] = []
        keyword_hits: List[SearchResult] = []
        try:
            semantic_hits = self.semantic_search(query)
        except EmbeddingServiceError as e:
            audit_log({"event": "retrieval_degraded", "path": "semantic", "error": str(e)})
        try:
            keyword_hits = self.keyword_search(query)
        except Exception as e:
            audit_log({"event": "retrieval_degraded", "path": "keyword", "error": str(e)})

        if not semantic_hits and not keyword_hits:
            return []
        if not semantic_hits:
            return keyword_hits
        if not keyword_hits:
            return semantic_hits

        scores = {}
        semantic_meta = {}
        keyword_meta = {}

        for rank, hit in enumerate(semantic_hits):
            key = (hit.source, hit.chunk_id)
            contrib = 1 / (self.rrf_k + rank)
            scores[key] = scores.get(key, 0) + contrib
            semantic_meta[key] = {"rank": rank, "score": hit.score, "rrf_contrib": contrib,
                                   "text": hit.text, "stem_tags": hit.stem_tags}

        for rank, hit in enumerate(keyword_hits):
            key = (hit.source, hit.chunk_id)
            contrib = 1 / (self.rrf_k + rank)
            scores[key] = scores.get(key, 0) + contrib
            keyword_meta[key] = {"rank": rank, "score": hit.score, "rrf_contrib": contrib,
                                  "text": hit.text, "stem_tags": hit.stem_tags}

        all_hits = {(h.source, h.chunk_id): h for h in semantic_hits + keyword_hits}
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        merged = []
        for (source, chunk_id), score in ranked:
            hit = all_hits[(source, chunk_id)]
            sm = semantic_meta.get((source, chunk_id))
            km = keyword_meta.get((source, chunk_id))
            merged.append(SearchResult(
                text=hit.text, score=score, source=source, chunk_id=chunk_id,
                stem_tags=hit.stem_tags, retrieval_mode="hybrid",
                semantic_score=sm["score"] if sm else None,
                semantic_rank=sm["rank"] if sm else None,
                keyword_score=km["score"] if km else None,
                keyword_rank=km["rank"] if km else None,
                rrf_score=score,
                rrf_semantic_contrib=sm["rrf_contrib"] if sm else None,
                rrf_keyword_contrib=km["rrf_contrib"] if km else None,
                provenance={"semantic": sm, "keyword": km}
            ))

        return merged[:max(self.top_k_semantic, self.top_k_keyword)]
