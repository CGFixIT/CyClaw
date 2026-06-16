"""Prompt injection filter and input sanitization.

Strips known injection patterns and validates input length.
Also used at index time to sanitize corpus chunks.

The filter is driven entirely by ``config.yaml`` (``policy.prompt_filter``):
``enabled``, ``banned_patterns`` and ``max_input_chars``. Patterns are
compiled once per config file and cached, so the hot path (every /query and
every chunk at index time) does not recompile regexes on each call.
"""

import re
from functools import lru_cache
from typing import List, Pattern, Tuple

import yaml

from utils.errors import PromptInjectionError

# Fallback used only when config.yaml omits policy.prompt_filter entirely.
_DEFAULT_MAX_INPUT_CHARS = 4000


@lru_cache(maxsize=8)
def _load_filter(config_path: str) -> Tuple[bool, int, Tuple[Pattern, ...]]:
    """Load and compile the prompt filter from config (cached per path).

    Returns ``(enabled, max_input_chars, compiled_patterns)``.
    """
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}

    pf = cfg.get("policy", {}).get("prompt_filter", {})
    enabled = pf.get("enabled", True)
    max_chars = pf.get("max_input_chars", _DEFAULT_MAX_INPUT_CHARS)
    patterns = tuple(
        re.compile(p, re.IGNORECASE) for p in pf.get("banned_patterns", [])
    )
    return enabled, max_chars, patterns


def check_input(query: str, config_path: str = "config.yaml") -> str:
    """Validate user input against length and injection rules.

    Returns the (unmodified) query when it passes so callers can use it inline.
    Raises :class:`PromptInjectionError` when the input is too long or matches a
    banned pattern. When the filter is disabled in config, input passes through.
    """
    enabled, max_chars, patterns = _load_filter(config_path)
    if not enabled:
        return query

    if len(query) > max_chars:
        raise PromptInjectionError(
            f"Input exceeds maximum length: {len(query)} chars (max {max_chars})",
            details={"length": len(query), "max": max_chars},
        )

    for pattern in patterns:
        if pattern.search(query):
            raise PromptInjectionError(
                "Potential prompt injection detected",
                details={"matched_pattern": pattern.pattern},
            )
    return query


def sanitize_chunk(text: str, config_path: str = "config.yaml") -> str:
    """Replace banned patterns in a corpus chunk with ``[FILTERED]``.

    Used at index time so injected instructions stored in the corpus cannot
    later be surfaced as retrieved context. No-op when the filter is disabled.
    """
    enabled, _max_chars, patterns = _load_filter(config_path)
    if not enabled:
        return text

    for pattern in patterns:
        text = pattern.sub("[FILTERED]", text)
    return text
