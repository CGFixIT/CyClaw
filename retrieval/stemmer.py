"""
Enhanced Porter-like stemmer — optimized for technical/AI vocabulary.

Extends NLTK PorterStemmer with custom rules for:
- AI/ML terms (embedding, transformer, attention, etc.)
- DevOps/infra terms (kubernetes, docker, nginx, etc.)
- PsyClaw-domain terms (retrieval, augmented, langgraph, etc.)
"""

import re
from functools import lru_cache
from typing import List
from nltk.stem import PorterStemmer
from nltk.tokenize import word_tokenize
import nltk
nltk.download('punkt', quiet=True)
nltk.download('punkt_tab', quiet=True)

_stemmer = PorterStemmer()

# Token filter: must start with a letter, then 1+ alphanumerics/_/-.
# Compiled once at import instead of on every tokenize_and_stem() call.
_TOKEN_RE = re.compile(r'^[a-z][a-z0-9_-]{1,}$')

_CUSTOM_STEMS = {
    "embedding": "embed", "embeddings": "embed",
    "transformer": "transform", "transformers": "transform",
    "attention": "attn", "attentional": "attn",
    "retrieval": "retriev", "retrieve": "retriev", "retrieved": "retriev",
    "augmented": "augment", "augmentation": "augment",
    "kubernetes": "k8s", "docker": "docker", "nginx": "nginx",
    "langgraph": "langgraph", "langchain": "langchain",
    "chromadb": "chroma", "chroma": "chroma",
    "psyclaw": "psyclaw", "safeclaw": "safeclaw",
    "personality": "person", "soul": "soul",
}

@lru_cache(maxsize=100_000)
def stem_token(token: str) -> str:
    lower = token.lower()
    if lower in _CUSTOM_STEMS:
        return _CUSTOM_STEMS[lower]
    return _stemmer.stem(lower)

def tokenize_and_stem(text: str) -> List[str]:
    tokens = word_tokenize(text.lower())
    return [
        stem_token(t) for t in tokens
        if _TOKEN_RE.match(t)
    ]
