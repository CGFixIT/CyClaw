"""Unit tests for Porter stemmer."""

import pytest
from retrieval.stemmer import stem_token, tokenize_and_stem

def test_custom_stem_embedding():
    assert stem_token("embedding") == "embed"
    assert stem_token("embeddings") == "embed"

def test_custom_stem_retrieval():
    assert stem_token("retrieval") == "retriev"
    assert stem_token("retrieve") == "retriev"

def test_custom_stem_transformer():
    assert stem_token("transformer") == "transform"
    assert stem_token("transformers") == "transform"

def test_psyclaw_domain_terms():
    assert stem_token("psyclaw") == "psyclaw"
    assert stem_token("chromadb") == "chroma"
    assert stem_token("langgraph") == "langgraph"

def test_tokenize_and_stem_filters_short():
    result = tokenize_and_stem("a to the")
    assert result == []

def test_tokenize_and_stem_basic():
    result = tokenize_and_stem("retrieve embeddings from chromadb")
    assert "retriev" in result
    assert "embed" in result
    assert "chroma" in result
