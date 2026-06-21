"""Local embedding service using sentence-transformers.

CPU-only. No Ollama. No external service required.
Caches the model AND the parsed config across calls to avoid reload/reparse
overhead on the hot query path.

Security note (2026-06):
- We delegate model loading to sentence-transformers.
- Prefer safetensors format for any custom or local models.
- Historical: CVE-2025-32434 showed that torch.load(..., weights_only=True) was bypassable for RCE on torch<2.6.0.
- We now pin torch==2.6.0+cpu (see pyproject.toml) and treat untrusted .pth/.bin files as high risk.
- Model weights should come from verified/trusted sources only (HF official or local hashed files).
"""

import os
from functools import lru_cache
from typing import List

import yaml

os.environ["TOKENIZERS_PARALLELISM"] = "false"

@lru_cache(maxsize=1)
def _load_model(model_name: str, cache_dir: str):
    """Load SentenceTransformer with security-conscious defaults.

    Note: sentence-transformers will use safetensors when available.
    If a .pth or .bin file is explicitly provided via model_name, it may still
    hit torch.load paths. Treat such cases as requiring extra scrutiny.
    """
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model_name, cache_folder=cache_dir or None)

@lru_cache(maxsize=8)
def _embeddings_cfg(config_path: str) -> tuple:
    """Read models.embeddings from config once per path (cached).

    Returns (model_name, cache_dir). Uses a context manager so the config file
    handle is always closed -- the previous ``yaml.safe_load(open(path))`` form
    leaked a descriptor on every call.
    """
    with open(config_path, encoding="utf-8") as f:
        emb_cfg = yaml.safe_load(f)["models"]["embeddings"]
    return emb_cfg["model"], emb_cfg.get("cache_dir", "")

@lru_cache(maxsize=2048)
def _cached_embedding(text: str, config_path: str) -> tuple:
    """Memoize query embeddings keyed on (text, config_path).

    Encoding a query is a full SentenceTransformer forward pass -- the most
    expensive step on the retrieval hot path. Identical queries (common in
    practice) previously re-ran the model every time. The cached value is an
    immutable tuple so it can be safely shared across callers.
    """
    model_name, cache_dir = _embeddings_cfg(config_path)
    model = _load_model(model_name, cache_dir)
    return tuple(model.encode(text, normalize_embeddings=True).tolist())

def get_embedding(text: str, config_path: str = "config.yaml") -> List[float]:
    return list(_cached_embedding(text, config_path))

def reset_embedding_cache() -> None:
    """Clear the memoized query-embedding cache (e.g. after a model swap)."""
    _cached_embedding.cache_clear()

def get_embeddings_batch(texts: List[str], config_path: str = "config.yaml") -> List[List[float]]:
    model_name, cache_dir = _embeddings_cfg(config_path)
    model = _load_model(model_name, cache_dir)
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=True).tolist()
