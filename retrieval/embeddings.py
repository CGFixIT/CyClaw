"""Local embedding service using sentence-transformers.

CPU-only. No Ollama. No external service required.
Caches the model across calls to avoid reload overhead.
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

def get_embedding(text: str, config_path: str = "config.yaml") -> List[float]:
    cfg = yaml.safe_load(open(config_path))
    emb_cfg = cfg["models"]["embeddings"]
    model = _load_model(emb_cfg["model"], emb_cfg.get("cache_dir", ""))
    return model.encode(text, normalize_embeddings=True).tolist()

def get_embeddings_batch(texts: List[str], config_path: str = "config.yaml") -> List[List[float]]:
    cfg = yaml.safe_load(open(config_path))
    emb_cfg = cfg["models"]["embeddings"]
    model = _load_model(emb_cfg["model"], emb_cfg.get("cache_dir", ""))
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=True).tolist()
