"""Tests for utils.config_validation.validate_retrieval_config."""

from __future__ import annotations

import pytest

from utils.config_validation import validate_retrieval_config
from utils.errors import ConfigError


def _valid_retrieval() -> dict:
    """The shipped config.yaml defaults -- must always validate."""
    return {
        "retrieval": {
            "top_k_semantic": 5,
            "top_k_keyword": 5,
            "rrf_k": 60,
            "min_score": 0.028,
        }
    }


def test_shipped_defaults_pass():
    validate_retrieval_config(_valid_retrieval())  # must not raise


def test_min_score_zero_and_one_are_inclusive():
    for boundary in (0, 1, 0.0, 1.0):
        cfg = _valid_retrieval()
        cfg["retrieval"]["min_score"] = boundary
        validate_retrieval_config(cfg)  # must not raise


@pytest.mark.parametrize("bad", [1.5, -0.1, 2, -1, "0.5", None, True])
def test_min_score_out_of_range_or_wrong_type_rejected(bad):
    cfg = _valid_retrieval()
    cfg["retrieval"]["min_score"] = bad
    with pytest.raises(ConfigError):
        validate_retrieval_config(cfg)


@pytest.mark.parametrize("key", ["top_k_semantic", "top_k_keyword", "rrf_k"])
@pytest.mark.parametrize("bad", [0, -1, 1.5, "5", None, True])
def test_positive_int_keys_reject_bad_values(key, bad):
    cfg = _valid_retrieval()
    cfg["retrieval"][key] = bad
    with pytest.raises(ConfigError):
        validate_retrieval_config(cfg)


def test_missing_retrieval_block_rejected():
    with pytest.raises(ConfigError):
        validate_retrieval_config({})


def test_retrieval_block_not_a_mapping_rejected():
    with pytest.raises(ConfigError):
        validate_retrieval_config({"retrieval": [1, 2, 3]})


def test_error_message_names_the_offending_key():
    cfg = _valid_retrieval()
    cfg["retrieval"]["rrf_k"] = -5
    with pytest.raises(ConfigError) as exc:
        validate_retrieval_config(cfg)
    assert "rrf_k" in str(exc.value)
