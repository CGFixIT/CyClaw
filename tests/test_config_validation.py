"""Tests for utils.config_validation validators."""

from __future__ import annotations

import pytest

from utils.config_validation import validate_personality_config, validate_retrieval_config
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


# ── validate_personality_config ──────────────────────────────────────────


def _valid_personality() -> dict:
    return {"personality": {"enabled": True, "soul_max_chars": 8000}}


def test_personality_shipped_defaults_pass():
    validate_personality_config(_valid_personality())


def test_personality_disabled_skips_validation():
    validate_personality_config({"personality": {"enabled": False, "soul_max_chars": -1}})


def test_personality_absent_block_skips_validation():
    validate_personality_config({})


@pytest.mark.parametrize("bad", [0, -1, "8000", True, 0.5])
def test_personality_soul_max_chars_rejects_bad_values(bad):
    cfg = _valid_personality()
    cfg["personality"]["soul_max_chars"] = bad
    with pytest.raises(ConfigError):
        validate_personality_config(cfg)


def test_personality_soul_max_chars_omitted_passes():
    validate_personality_config({"personality": {"enabled": True}})


def test_personality_error_message_names_field():
    cfg = _valid_personality()
    cfg["personality"]["soul_max_chars"] = 0
    with pytest.raises(ConfigError) as exc:
        validate_personality_config(cfg)
    assert "soul_max_chars" in str(exc.value)
