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
from pathlib import Path
from typing import Optional

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

    root = logging.getLogger("psyclaw")
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
        with open(config_path) as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache

def reset_config_cache() -> None:
    global _config_cache
    _config_cache = None

def hash_query(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()

def redact_sensitive(text: str, cfg: Optional[dict] = None) -> str:
    if cfg is None:
        cfg = _get_config()
    privacy = cfg.get("policy", {}).get("privacy", {})
    if privacy.get("redact_emails", False):
        text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[REDACTED_EMAIL]', text)
    if privacy.get("redact_ips", False):
        text = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[REDACTED_IP]', text)
    for pattern in privacy.get("redact_secrets_like", []):
        try:
            text = re.sub(pattern, '[REDACTED_SECRET]', text)
        except re.error:
            pass
    return text

def audit_log(event: dict, config_path: str = "config.yaml") -> None:
    cfg = _get_config(config_path)
    log_path = Path(cfg["logging"]["audit_file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    audit_fields = cfg["logging"].get("audit_fields", {})
    if "query" in event and audit_fields.get("include_query_hash", True):
        raw_query = event.pop("query")
        event["query_hash"] = hash_query(raw_query)
    for key, value in event.items():
        if isinstance(value, str) and key not in ("query_hash", "timestamp", "event"):
            event[key] = redact_sensitive(value, cfg)
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(log_path, "a") as f:
        f.write(json.dumps(event) + "\n")
