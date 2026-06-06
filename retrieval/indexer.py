"""Build ChromaDB (semantic) and BM25 (keyword) indices from .md corpus.

Uses sentence-transformers for embeddings (CPU, no Ollama).
Sanitizes chunks at ingestion time via prompt filter.
"""

import json
import os
import pickle
from pathlib import Path
from typing import List, Tuple

import chromadb
from chromadb.config import Settings
from rank_bm25 import BM25Okapi
import yaml

from .stemmer import tokenize_and_stem
from .embeddings import get_embeddings_batch
from utils.errors import CorpusEmptyError
from utils.sanitizer import sanitize_chunk

def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)

def load_corpus(corpus_path: str, extensions: List[str]) -> List[Tuple[str, str]]:
    docs = []
    corpus_dir = Path(corpus_path)
    if not corpus_dir.exists():
        raise CorpusEmptyError(f"Corpus directory does not exist: {corpus_path}")
    for ext in extensions:
        for file_path in corpus_dir.rglob(f"*{ext}"):
            try:
                content = file_path.read_text(encoding="utf-8")
                docs.append((str(file_path), content))
            except Exception as e:
                print(f"[WARN] Skipping {file_path}: {e}")
    if not docs:
        raise CorpusEmptyError(f"No documents found in {corpus_path} with extensions {extensions}")
    return docs

def chunk_document(text: str, chunk_size: int = 512, overlap: int = 50) -> List[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks

def build_index(config_path: str = "config.yaml") -> None:
    cfg = load_config(config_path)
    corpus_path = cfg["corpus"]["path"]
    extensions = cfg["corpus"]["extensions"]
    chroma_path = cfg["indexing"]["chroma_path"]
    bm25_path = cfg["indexing"]["bm25_path"]
    collection_name = cfg["indexing"]["collection_name"]
    chunk_size = cfg["indexing"]["chunk_size"]
    chunk_overlap = cfg["indexing"]["chunk_overlap"]
    batch_size = cfg["indexing"]["batch_size"]

    print(f"[Indexer] Loading corpus from {corpus_path}")
    docs = load_corpus(corpus_path, extensions)
    print(f"[Indexer] Loaded {len(docs)} documents")

    all_chunks = []
    all_metadata = []

    for source, content in docs:
        chunks = chunk_document(content, chunk_size, chunk_overlap)
        for i, chunk in enumerate(chunks):
            clean_chunk = sanitize_chunk(chunk)
            stem_tags = tokenize_and_stem(clean_chunk)[:20]
            all_chunks.append(clean_chunk)
            all_metadata.append({
                "source": source,
                "chunk_id": i,
                "stem_tags": json.dumps(stem_tags)
            })

    print(f"[Indexer] Total chunks: {len(all_chunks)}")

    Path(chroma_path).mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=chroma_path,
        settings=Settings(anonymized_telemetry=False)
    )
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.create_collection(collection_name)

    print("[Indexer] Building ChromaDB (semantic) index...")
    for batch_start in range(0, len(all_chunks), batch_size):
        batch_end = min(batch_start + batch_size, len(all_chunks))
        batch_chunks = all_chunks[batch_start:batch_end]
        batch_meta = all_metadata[batch_start:batch_end]
        batch_embeddings = get_embeddings_batch(batch_chunks)
        batch_ids = [f"chunk_{batch_start + i}" for i in range(len(batch_chunks))]
        collection.add(
            documents=batch_chunks,
            embeddings=batch_embeddings,
            metadatas=batch_meta,
            ids=batch_ids
        )
        print(f"[Indexer] Indexed {batch_end}/{len(all_chunks)} chunks")

    print("[Indexer] Building BM25 (keyword) index...")
    tokenized_corpus = [tokenize_and_stem(chunk) for chunk in all_chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    Path(bm25_path).parent.mkdir(parents=True, exist_ok=True)
    with open(bm25_path, "wb") as f:
        pickle.dump({"bm25": bm25, "chunks": all_chunks, "metadata": all_metadata}, f)

    print(f"[Indexer] Done. ChromaDB: {chroma_path}, BM25: {bm25_path}")

if __name__ == "__main__":
    build_index()
