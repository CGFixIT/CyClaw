"""Startup validation for config.yaml tunables.

Validates ``retrieval`` and ``personality`` blocks at boot so typos like
``min_score: 1.5`` or ``soul_max_chars: 0`` surface as a clear ``ConfigError``
instead of silent mis-routing or empty-prompt degradation at request time.

Mirrors the dataclass ``__post_init__`` validation that ``sync/config.py`` and
``agentic/config.py`` already perform for their blocks.
"""

from __future__ import annotations

from typing import Any

from utils.errors import ConfigError

# Tunables that must be positive integers (they index ranked result lists and
# appear in the RRF weight denominator ``1 / (rrf_k + rank)``).
_POSITIVE_INT_KEYS = ("top_k_semantic", "top_k_keyword", "rrf_k")


def _is_real_number(value: Any) -> bool:
    """True for int/float but NOT bool (bool is an int subclass in Python)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_retrieval_config(cfg: dict[str, Any]) -> None:
    """Validate ``cfg['retrieval']``. Raise ``ConfigError`` on any invalid value.

    Checks:
      * the ``retrieval`` block exists and is a mapping;
      * ``min_score`` is a number in ``[0, 1]`` (RRF-fused scores live there);
      * ``top_k_semantic`` / ``top_k_keyword`` / ``rrf_k`` are positive integers.

    Valid configs (the shipped defaults: ``min_score: 0.028``, ``top_k_*: 5``,
    ``rrf_k: 60``) pass unchanged -- this only rejects out-of-range typos.
    """
    retrieval = cfg.get("retrieval")
    if not isinstance(retrieval, dict):
        raise ConfigError(
            "config.retrieval block is missing or not a mapping",
            details={"received_type": type(retrieval).__name__},
        )

    min_score = retrieval.get("min_score")
    if not _is_real_number(min_score) or not 0 <= min_score <= 1:
        raise ConfigError(
            f"retrieval.min_score must be a number in [0, 1], got: {min_score!r}",
            details={"received": min_score},
        )

    for key in _POSITIVE_INT_KEYS:
        val = retrieval.get(key)
        if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
            raise ConfigError(
                f"retrieval.{key} must be a positive integer, got: {val!r}",
                details={"received": val, "key": key},
            )


def validate_personality_config(cfg: dict[str, Any]) -> None:
    """Validate ``cfg['personality']`` when the subsystem is enabled.

    Checks:
      * ``soul_max_chars`` is a positive integer (0 silently truncates the soul
        to empty, dropping personality from every LLM prompt with no warning).

    No-op when ``personality.enabled`` is false or the block is absent.
    """
    personality = cfg.get("personality")
    if not isinstance(personality, dict) or not personality.get("enabled", False):
        return

    soul_max_chars = personality.get("soul_max_chars")
    if soul_max_chars is not None:
        if not isinstance(soul_max_chars, int) or isinstance(soul_max_chars, bool) or soul_max_chars <= 0:
            raise ConfigError(
                f"personality.soul_max_chars must be a positive integer, got: {soul_max_chars!r}",
                details={"received": soul_max_chars},
            )
