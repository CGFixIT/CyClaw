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
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

import yaml

_logging_initialized = False


def setup_logging(cfg: Optional[dict] = None) -> None:
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

_config_cache: Optional[dict] = None

def _get_config(config_path: str = "config.yaml") -> dict:
    global _config_cache
    if _config_cache is None:
        with open(config_path, encoding="utf-8") as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache

def reset_config_cache() -> None:
    global _config_cache
    _config_cache = None

def hash_query(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()

@lru_cache(maxsize=8)
def _compiled_redactors(
    redact_emails: bool, redact_ips: bool, secret_patterns: Tuple[str, ...]
) -> Tuple[Tuple[re.Pattern, str], ...]:
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

def redact_sensitive(text: str, cfg: Optional[dict] = None) -> str:
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

def audit_log(event: dict, config_path: str = "config.yaml") -> None:
    cfg = _get_config(config_path)
    log_path = Path(cfg["logging"]["audit_file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    audit_fields = cfg["logging"].get("audit_fields", {})
    record = dict(event)  # work on a shallow copy — never mutate the caller's dict
    if "query" in record and audit_fields.get("include_query_hash", True):
        raw_query = record.pop("query")
        record["query_hash"] = hash_query(raw_query)
    for key, value in list(record.items()):
        if isinstance(value, str) and key not in ("query_hash", "timestamp", "event"):
            record[key] = redact_sensitive(value, cfg)
    record["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
