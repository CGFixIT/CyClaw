"""Unit tests for retrieval/embeddings.py — the query-embedding cache layer.

embeddings.py had no dedicated test; it was only exercised indirectly via
test_indexer.py mocking ``get_embeddings_batch``. The memoization that the
module docstring calls out as the retrieval hot-path optimization
(``_cached_embedding`` lru_cache + ``reset_embedding_cache``) had no regression
test proving a repeat query is a cache hit. The heavy SentenceTransformer load
(``_load_model``) is mocked, so no model download is required.
"""

import pytest
import yaml

from retrieval import embeddings


def _write_cfg(tmp_path, model="test-model", cache_dir=""):
    cfg = {"models": {"embeddings": {"model": model, "cache_dir": cache_dir}}}
    p = tmp_path / "config.yaml"
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f)
    return str(p)


class _Arr:
    """Minimal stand-in for the numpy array returned by SentenceTransformer.encode."""

    def __init__(self, data):
        self._data = data

    def tolist(self):
        return self._data


class _FakeModel:
    def __init__(self):
        self.calls = 0

    def encode(self, text, normalize_embeddings=True, show_progress_bar=False):
        self.calls += 1
        if isinstance(text, list):
            return _Arr([[float(len(t)), 0.5] for t in text])
        return _Arr([float(len(text)), 0.5])


@pytest.fixture(autouse=True)
def _reset_caches():
    embeddings._cached_embedding.cache_clear()
    embeddings._embeddings_cfg.cache_clear()
    yield
    embeddings._cached_embedding.cache_clear()
    embeddings._embeddings_cfg.cache_clear()


@pytest.fixture
def fake_model(monkeypatch):
    model = _FakeModel()
    monkeypatch.setattr(embeddings, "_load_model", lambda name, cache: model)
    return model


class TestGetEmbedding:
    def test_returns_plain_list(self, tmp_path, fake_model):
        cfg_path = _write_cfg(tmp_path)
        out = embeddings.get_embedding("hello", cfg_path)
        assert isinstance(out, list)
        assert out == [5.0, 0.5]  # len("hello") == 5

    def test_repeat_query_is_a_cache_hit(self, tmp_path, fake_model):
        cfg_path = _write_cfg(tmp_path)
        embeddings.get_embedding("same query", cfg_path)
        embeddings.get_embedding("same query", cfg_path)
        # Second identical call served from the lru_cache -> model ran only once.
        assert fake_model.calls == 1

    def test_distinct_queries_each_encode(self, tmp_path, fake_model):
        cfg_path = _write_cfg(tmp_path)
        embeddings.get_embedding("query one", cfg_path)
        embeddings.get_embedding("query two", cfg_path)
        assert fake_model.calls == 2


class TestResetCache:
    def test_reset_forces_recompute(self, tmp_path, fake_model):
        cfg_path = _write_cfg(tmp_path)
        embeddings.get_embedding("q", cfg_path)
        assert fake_model.calls == 1
        embeddings.reset_embedding_cache()
        embeddings.get_embedding("q", cfg_path)
        # After a cache clear the same query must re-run the model.
        assert fake_model.calls == 2


class TestEmbeddingsCfg:
    def test_reads_model_and_cache_dir(self, tmp_path):
        cfg_path = _write_cfg(tmp_path, model="my-model", cache_dir="/tmp/cache")
        assert embeddings._embeddings_cfg(cfg_path) == ("my-model", "/tmp/cache")

    def test_cfg_cached_per_path(self, tmp_path):
        cfg_path = _write_cfg(tmp_path)
        first = embeddings._embeddings_cfg(cfg_path)
        second = embeddings._embeddings_cfg(cfg_path)
        assert first is second  # served from the per-path cache


class TestBatch:
    def test_batch_encodes_all_texts(self, tmp_path, fake_model):
        cfg_path = _write_cfg(tmp_path)
        out = embeddings.get_embeddings_batch(["a", "bb", "ccc"], cfg_path)
        assert out == [[1.0, 0.5], [2.0, 0.5], [3.0, 0.5]]
        assert fake_model.calls == 1  # one batched encode call
