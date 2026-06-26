"""Build ChromaDB (semantic) and BM25 (keyword) indices from .md corpus.

Uses sentence-transformers for embeddings (CPU, no Ollama).
Sanitizes chunks at ingestion time via prompt filter.
"""

import json
import logging
from pathlib import Path

import yaml

from utils.errors import CorpusEmptyError
from utils.sanitizer import sanitize_chunk

from .embeddings import get_embeddings_batch
from .stemmer import tokenize_and_stem
from .vector_store import get_vector_writer, vector_backend

logger = logging.getLogger(__name__)


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_corpus(corpus_path: str, extensions: list[str]) -> list[tuple[str, str]]:
    docs = []
    corpus_dir = Path(corpus_path)
    if not corpus_dir.exists():
        raise CorpusEmptyError(f"Corpus directory does not exist: {corpus_path}")
    corpus_resolved = corpus_dir.resolve()
    normalized_extensions = {ext.lower() for ext in extensions}
    for file_path in corpus_dir.rglob("*"):
        if not file_path.is_file():
            continue
        # Match file extension case-insensitively (e.g., .MD matches .md config entry).
        if file_path.suffix.lower() not in normalized_extensions:
            continue
        # Reject symlinks that escape the corpus directory — rglob follows
        # symlinks by default, so a link pointing outside data/corpus could
        # pull arbitrary filesystem content into the index.
        if not file_path.resolve().is_relative_to(corpus_resolved):
            logger.warning("Skipping %s: resolves outside corpus directory", file_path)
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
            docs.append((str(file_path), content))
        except Exception as e:
            logger.warning("Skipping %s: %s", file_path, e)
    if not docs:
        raise CorpusEmptyError(f"No documents found in {corpus_path} with extensions {extensions}")
    return docs

def chunk_document(text: str, chunk_size: int = 512, overlap: int = 50) -> list[str]:
    # The stride must advance by at least one word per iteration. If a
    # misconfiguration sets overlap >= chunk_size, ``chunk_size - overlap`` is
    # <= 0 and ``start`` never moves forward — the loop spins forever, appending
    # identical chunks until the indexer exhausts memory. Clamp the step to a
    # minimum of 1 so a bad config degrades to slow-but-finite instead of hanging.
    step = max(1, chunk_size - overlap)
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        start += step
    return chunks

def build_index(config_path: str = "config.yaml") -> None:
    cfg = load_config(config_path)
    corpus_path = cfg["corpus"]["path"]
    extensions = cfg["corpus"]["extensions"]
    bm25_path = cfg["indexing"]["bm25_path"]
    chunk_size = cfg["indexing"]["chunk_size"]
    chunk_overlap = cfg["indexing"]["chunk_overlap"]
    batch_size = cfg["indexing"]["batch_size"]

    # Fail fast on chunking misconfiguration rather than building a corrupt index.
    # chunk_size < 1 makes every window empty (end == start), so collection.add()
    # ingests blank documents. chunk_overlap >= chunk_size forces the stride down
    # to a single word, exploding a modest corpus into one chunk per word and
    # exhausting memory. The chunk_document() max(1, ...) clamp keeps direct
    # callers finite, but the config boundary is where a human-set value belongs.
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) must be < chunk_size ({chunk_size})"
        )

    logger.info("Loading corpus from %s", corpus_path)
    docs = load_corpus(corpus_path, extensions)
    logger.info("Loaded %d documents", len(docs))

    all_chunks = []
    all_metadata = []
    # Tokenize each chunk exactly once. The full token list feeds the BM25
    # index; the first 20 tokens become the stem_tags metadata. Re-tokenizing
    # the whole corpus a second time for BM25 (the previous behaviour) doubled
    # the regex/stemming work at index time for no benefit.
    tokenized_corpus = []

    for source, content in docs:
        chunks = chunk_document(content, chunk_size, chunk_overlap)
        for i, chunk in enumerate(chunks):
            clean_chunk = sanitize_chunk(chunk, config_path)
            tokens = tokenize_and_stem(clean_chunk)
            all_chunks.append(clean_chunk)
            tokenized_corpus.append(tokens)
            all_metadata.append({
                "source": source,
                "chunk_id": i,
                "stem_tags": json.dumps(tokens[:20])
            })

    logger.info("Total chunks: %d", len(all_chunks))

    # Semantic (vector) index. The backend is pluggable — ChromaDB by default
    # (embedded, offline-first), or pgvector when indexing.vector_backend=pgvector.
    # Cosine space / `1 - distance` scoring and the per-chunk metadata are identical
    # across backends, so RRF order and the min_score gate are unaffected (PR #99
    # #1/#6); only where the vectors live changes.
    backend = vector_backend(cfg)
    writer = get_vector_writer(cfg)
    writer.reset()
    logger.info("Building semantic (vector) index [%s]...", backend)
    try:
        for batch_start in range(0, len(all_chunks), batch_size):
            batch_end = min(batch_start + batch_size, len(all_chunks))
            batch_chunks = all_chunks[batch_start:batch_end]
            batch_meta = all_metadata[batch_start:batch_end]
            batch_embeddings = get_embeddings_batch(batch_chunks, config_path)
            batch_ids = [f"chunk_{batch_start + i}" for i in range(len(batch_chunks))]
            writer.add(batch_ids, batch_chunks, batch_embeddings, batch_meta)
            logger.info("Indexed %d/%d chunks", batch_end, len(all_chunks))
        writer.finalize()
    finally:
        writer.close()

    logger.info("Building BM25 (keyword) index...")
    # tokenized_corpus was built alongside all_chunks above (single tokenization pass).
    Path(bm25_path).parent.mkdir(parents=True, exist_ok=True)
    with open(bm25_path, "w", encoding="utf-8") as f:
        json.dump({
            "tokenized_corpus": tokenized_corpus,
            "chunks": all_chunks,
            "metadata": all_metadata,
        }, f)

    logger.info("Done. Semantic backend: %s, BM25: %s", backend, bm25_path)

def main() -> None:
    """Console entry point for ``cyclaw-index`` (see pyproject [project.scripts]).

    Thin wrapper over :func:`build_index`. The declared
    ``cyclaw-index = "retrieval.indexer:main"`` script previously raised
    AttributeError because this module only defined ``build_index``.

    Configures root logging here (not at import time) so the CLI keeps showing
    progress, while importers of ``build_index`` control their own log handlers.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    build_index()


if __name__ == "__main__":
    main()
