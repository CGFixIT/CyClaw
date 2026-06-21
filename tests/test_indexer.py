"""Unit tests for retrieval.indexer chunking and config validation.

Covers chunk_document edge cases and the build_index fail-fast guards that
reject chunking misconfiguration before a corrupt index can be written.
"""

from unittest.mock import MagicMock, patch

import pytest
import yaml

from retrieval.indexer import chunk_document, build_index


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
        with patch("retrieval.indexer.get_embeddings_batch", fake_embeddings), \
                patch("retrieval.indexer.chromadb") as mock_chromadb:
            mock_client = MagicMock()
            mock_client.create_collection.return_value = MagicMock()
            mock_chromadb.PersistentClient.return_value = mock_client
            build_index(str(config_path))

        assert fake_embeddings.called, "get_embeddings_batch was never called"
        args, kwargs = fake_embeddings.call_args
        passed_config = args[1] if len(args) > 1 else kwargs.get("config_path")
        assert passed_config == str(config_path), (
            "build_index did not forward its config_path to get_embeddings_batch; "
            f"got {passed_config!r}"
        )
