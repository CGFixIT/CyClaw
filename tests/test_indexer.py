"""Unit tests for retrieval.indexer chunking and config validation.

Covers chunk_document edge cases and the build_index fail-fast guards that
reject chunking misconfiguration before a corrupt index can be written.
"""

from unittest.mock import MagicMock, patch

import pytest
import yaml

from retrieval.indexer import chunk_document, build_index, load_corpus


class TestChunkDocument:
    def test_empty_text_returns_no_chunks(self):
        assert chunk_document("") == []
        assert chunk_document("   ") == []

    def test_single_window_when_text_fits(self):
        text = "alpha beta gamma"
        chunks = chunk_document(text, chunk_size=512, overlap=50)
        assert chunks == ["alpha beta gamma"]

    def test_normal_chunk_count_and_overlap(self):
        # 10 words, size=4, overlap=2 -> stride 2 -> starts at 0,2,4,6,8 = 5 chunks.
        words = [f"w{i}" for i in range(10)]
        chunks = chunk_document(" ".join(words), chunk_size=4, overlap=2)
        assert len(chunks) == 5
        assert chunks[0] == "w0 w1 w2 w3"
        # Overlap: each chunk shares its first two words with the previous tail.
        assert chunks[1] == "w2 w3 w4 w5"
        assert chunks[-1] == "w8 w9"

    def test_no_overlap_partitions_exactly(self):
        words = [f"w{i}" for i in range(6)]
        chunks = chunk_document(" ".join(words), chunk_size=3, overlap=0)
        assert chunks == ["w0 w1 w2", "w3 w4 w5"]


class TestBuildIndexValidation:
    def _write_config(self, tmp_path, chunk_size, chunk_overlap):
        cfg = {
            "corpus": {"path": str(tmp_path / "corpus"), "extensions": [".md"]},
            "indexing": {
                "chroma_path": str(tmp_path / "chroma"),
                "bm25_path": str(tmp_path / "bm25.json"),
                "collection_name": "test_kb",
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "batch_size": 10,
            },
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)
        return str(config_file)

    def test_rejects_zero_chunk_size(self, tmp_path):
        config_path = self._write_config(tmp_path, chunk_size=0, chunk_overlap=0)
        with pytest.raises(ValueError, match="chunk_size must be >= 1"):
            build_index(config_path)

    def test_rejects_overlap_equal_to_chunk_size(self, tmp_path):
        config_path = self._write_config(tmp_path, chunk_size=512, chunk_overlap=512)
        with pytest.raises(ValueError, match="chunk_overlap .* must be < chunk_size"):
            build_index(config_path)

    def test_rejects_overlap_greater_than_chunk_size(self, tmp_path):
        config_path = self._write_config(tmp_path, chunk_size=100, chunk_overlap=200)
        with pytest.raises(ValueError, match="chunk_overlap .* must be < chunk_size"):
            build_index(config_path)


class TestBuildIndexConfigPropagation:
    """build_index must build the semantic index with the embedding model from
    the SAME config it was called with — not the default config.yaml.

    Query-time embeddings already honour config_path
    (HybridRetriever.semantic_search -> get_embedding(query, self.config_path)).
    If build_index embeds the corpus with a different model/dimension, the index
    and the query vectors disagree and semantic retrieval silently breaks. This
    test pins the contract that the config_path reaches get_embeddings_batch.
    """

    def test_config_path_reaches_embeddings(self, tmp_path):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "a.md").write_text("hello world cyclaw retrieval fusion", encoding="utf-8")
        cfg = {
            "corpus": {"path": str(corpus), "extensions": [".md"]},
            "indexing": {
                "chroma_path": str(tmp_path / "chroma"),
                "bm25_path": str(tmp_path / "bm25.json"),
                "collection_name": "test_kb",
                "chunk_size": 512,
                "chunk_overlap": 50,
                "batch_size": 10,
            },
        }
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)

        fake_embeddings = MagicMock(return_value=[[0.1, 0.2, 0.3]])
        # Stub the vector writer so build_index runs without a real ChromaDB/pgvector
        # store; the assertion below verifies config_path forwarding to embeddings.
        with patch("retrieval.indexer.get_embeddings_batch", fake_embeddings), \
                patch("retrieval.indexer.get_vector_writer") as mock_get_writer:
            mock_get_writer.return_value = MagicMock()
            build_index(str(config_path))

        assert fake_embeddings.called, "get_embeddings_batch was never called"
        args, kwargs = fake_embeddings.call_args
        passed_config = args[1] if len(args) > 1 else kwargs.get("config_path")
        assert passed_config == str(config_path), (
            "build_index did not forward its config_path to get_embeddings_batch; "
            f"got {passed_config!r}"
        )


class TestLoadCorpusCaseInsensitive:
    """load_corpus must match file extensions case-insensitively.

    On Linux/CI rglob(f"*{ext}") was case-sensitive; files with .MD or .TXT
    would be silently skipped if config specified [".md", ".txt"].
    This test validates case-insensitive extension matching on all platforms.
    """

    def test_config_uppercase_matches_lowercase_files(self, tmp_path):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        # Create files with lowercase extensions
        (corpus / "doc.md").write_text("content", encoding="utf-8")
        (corpus / "notes.txt").write_text("content", encoding="utf-8")
        # Config specifies UPPERCASE extensions (tests reverse case matching)
        docs = load_corpus(str(corpus), extensions=[".MD", ".TXT"])
        # Both files should be loaded despite config using uppercase extensions
        assert len(docs) == 2
        sources = {source for source, _ in docs}
        assert any("doc.md" in s for s in sources)
        assert any("notes.txt" in s for s in sources)

    def test_config_lowercase_matches_uppercase_files(self, tmp_path):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        # Create files with uppercase extensions (separate base names to avoid
        # Windows case-insensitivity collisions on NTFS)
        (corpus / "first.MD").write_text("content", encoding="utf-8")
        (corpus / "second.TXT").write_text("content", encoding="utf-8")
        # Config specifies lowercase extensions
        docs = load_corpus(str(corpus), extensions=[".md", ".txt"])
        # Both files should be loaded (extension match is case-insensitive)
        assert len(docs) == 2
        sources = {source for source, _ in docs}
        assert any("first.MD" in s for s in sources)
        assert any("second.TXT" in s for s in sources)

    def test_unmatched_extensions_still_skipped(self, tmp_path):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "doc.md").write_text("match", encoding="utf-8")
        (corpus / "other.json").write_text("skip", encoding="utf-8")
        docs = load_corpus(str(corpus), extensions=[".md"])
        # Only .md should be loaded; .json should be skipped
        assert len(docs) == 1
        assert "doc.md" in docs[0][0]
