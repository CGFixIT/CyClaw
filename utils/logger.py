"""Append-only audit logging with query hashing and privacy redaction,
plus standard Python logging setup for operational diagnostics.

Every query, miss, escalation, and error gets a JSONL line.
Query text is SHA256-hashed to prevent the audit log from becoming
a data exfiltration vector.
"""

import hashlib
import json
import logging
import re
import threading
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import yaml

_logging_initialized = False
_AUDIT_WRITE_LOCK = threading.Lock()


def setup_logging(cfg: dict | None = None) -> None:
    global _logging_initialized
    if _logging_initialized:
        return
    if cfg is None:
        cfg = _get_config()
    log_cfg = cfg.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = log_cfg.get("log_file", "")

    root = logging.getLogger("cyclaw")
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

    _logging_initialized = True

@lru_cache(maxsize=8)
def _get_config(config_path: str = "config.yaml") -> dict:
    resolved = str(Path(config_path).expanduser().resolve())
    with open(resolved, encoding="utf-8") as f:
        return yaml.safe_load(f)

def reset_config_cache() -> None:
    clear = getattr(_get_config, "cache_clear", None)
    if clear is not None:
        clear()

def hash_query(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()

@lru_cache(maxsize=8)
def _compiled_redactors(
    redact_emails: bool, redact_ips: bool, secret_patterns: tuple[str, ...]
) -> tuple[tuple[re.Pattern, str], ...]:
    """Compile the active redaction patterns once per privacy configuration.

    redact_sensitive runs on every audited field of every query; recompiling
    these regexes each call was pure overhead. Keyed on the (hashable) privacy
    settings so a config change still produces a fresh pattern set.
    """
    compiled = []
    if redact_emails:
        compiled.append((re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
                         '[REDACTED_EMAIL]'))
    if redact_ips:
        compiled.append((re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),
                         '[REDACTED_IP]'))
    for pattern in secret_patterns:
        try:
            compiled.append((re.compile(pattern), '[REDACTED_SECRET]'))
        except re.error:
            pass
    return tuple(compiled)

def redact_sensitive(text: str, cfg: dict | None = None) -> str:
    if cfg is None:
        cfg = _get_config()
    privacy = cfg.get("policy", {}).get("privacy", {})
    redactors = _compiled_redactors(
        privacy.get("redact_emails", False),
        privacy.get("redact_ips", False),
        tuple(privacy.get("redact_secrets_like", []) or []),
    )
    for pattern, replacement in redactors:
        text = pattern.sub(replacement, text)
    return text


# Keys whose top-level value must NOT be redacted: query_hash is already a SHA-256
# digest, timestamp is structural ISO-8601, and event is the event-type tag.
# Applied only at the OUTER record level — nested fields named the same inside a
# dict/list value have no special meaning and pass through normal redaction.
_AUDIT_SKIP_KEYS = frozenset(("query_hash", "timestamp", "event"))


def _redact_value(value: object, cfg: dict) -> object:
    """Recursively redact strings inside dicts and lists.

    audit_log previously only redacted top-level string fields, so an event
    like {"details": {"email": "u@example.com"}} or {"errors": ["...@..."]}
    landed in audit.jsonl with the email intact. Defense-in-depth: structured
    payloads from CLI shims and exception details can contain redact-eligible
    strings that the simple top-level loop walked past. Recurses through dict
    values and list/tuple elements; tuples are returned as lists because
    json.dumps emits both identically and the on-disk format must stay JSON.
    Non-string scalars (int/float/bool/None) pass through unchanged.
    """
    if isinstance(value, str):
        return redact_sensitive(value, cfg)
    if isinstance(value, dict):
        return {k: _redact_value(v, cfg) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(v, cfg) for v in value]
    return value


def audit_log(event: dict, config_path: str = "config.yaml", cfg: dict | None = None) -> None:
    if cfg is None:
        cfg = _get_config(config_path)
    log_path = Path(cfg["logging"]["audit_file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    audit_fields = cfg["logging"].get("audit_fields", {})
    record = dict(event)  # work on a shallow copy — never mutate the caller's dict
    if "query" in record and audit_fields.get("include_query_hash", True):
        raw_query = record.pop("query")
        record["query_hash"] = hash_query(raw_query)
    for key, value in list(record.items()):
        if key in _AUDIT_SKIP_KEYS:
            continue
        record[key] = _redact_value(value, cfg)
    record["timestamp"] = datetime.now(UTC).isoformat()
    line = json.dumps(record) + "\n"
    with _AUDIT_WRITE_LOCK:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
