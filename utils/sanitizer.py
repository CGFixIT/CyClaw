"""Prompt injection filter and input sanitization.

Strips known injection patterns and validates input length.
Also used at index time to sanitize corpus chunks.
"""

import re
from utils.errors import PromptInjectionError

BANNED_PATTERNS = [
    r"ignore\s+(previous|all|prior)\s+instructions",
    r"ignore\s+all\s+previous",
    r"disregard\s+(previous|all|prior)",
    r"forget\s+(previous|all|prior)\s+instructions",
    r"new\s+instructions\s*:",
    r"system\s+prompt\s*:",
    r"you\s+are\s+now",
    r"pretend\s+(you\s+are|to\s+be)",
    r"act\s+as",
    r"jailbreak",
    r"DAN\s+mode",
    r"developer\s+mode",
    r"override\s+instructions",
]

MAX_INPUT_CHARS = 4000

def check_input(query: str) -> None:
    if len(query) > MAX_INPUT_CHARS:
        raise PromptInjectionError(
            f"Input too long: {len(query)} chars (max {MAX_INPUT_CHARS})",
            details={"length": len(query), "max": MAX_INPUT_CHARS}
        )
    for pattern in BANNED_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE):
            raise PromptInjectionError(
                f"Potential prompt injection detected",
                details={"matched_pattern": pattern}
            )

def sanitize_chunk(text: str) -> str:
    for pattern in BANNED_PATTERNS:
        text = re.sub(pattern, "[FILTERED]", text, flags=re.IGNORECASE)
    return text
