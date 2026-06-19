"""Local embedding service using sentence-transformers.

CPU-only. No Ollama. No external service required.
Caches the model AND the parsed config across calls to avoid reload/reparse
overhead on the hot query path.
"""

import os
import yaml
from typing import List
from functools import lru_cache

os.environ["TOKENIZERS_PARALLELISM"] = "false"

@lru_cache(maxsize=1)
def _load_model(model_name: str, cache_dir: str):
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

def get_embedding(text: str, config_path: str = "config.yaml") -> List[float]:
    model_name, cache_dir = _embeddings_cfg(config_path)
    model = _load_model(model_name, cache_dir)
    return model.encode(text, normalize_embeddings=True).tolist()

def get_embeddings_batch(texts: List[str], config_path: str = "config.yaml") -> List[List[float]]:
    model_name, cache_dir = _embeddings_cfg(config_path)
    model = _load_model(model_name, cache_dir)
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=True).tolist()
