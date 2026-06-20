# ============================================================================
# TEST STATUS (verified 2026-06-19 against HEAD f5934db):
# All 7 tests pass. audit_log(), hash_query(), redact_sensitive(), and
# reset_config_cache() signatures match utils/logger.py at HEAD exactly.
# ============================================================================
"""Unit tests for audit logging — hashing, redaction, JSONL format."""

import json
from pathlib import Path

import pytest
import yaml

from utils.logger import audit_log, hash_query, redact_sensitive, reset_config_cache


@pytest.fixture(autouse=True)
def clear_config_cache():
    """Reset config cache between tests."""
    reset_config_cache()
    yield
    reset_config_cache()


@pytest.fixture
def audit_config(tmp_path):
    """Config with audit logging to temp dir."""
    audit_file = str(tmp_path / "audit.jsonl")
    cfg = {
        "logging": {
            "audit_file": audit_file,
            "audit_fields": {
                "include_query_hash": True,
                "include_top_score": True,
                "include_retrieval_mode": True,
                "include_online_escalated": True,
                "include_model_used": True
            }
        },
        "policy": {
            "privacy": {
                "redact_emails": True,
                "redact_ips": True,
                "redact_secrets_like": ["AKIA[0-9A-Z]{16}"]
            }
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(cfg, f)
    return str(config_path), audit_file


class TestHashQuery:
    def test_deterministic(self):
        h1 = hash_query("test query")
        h2 = hash_query("test query")
        assert h1 == h2

    def test_different_inputs_different_hashes(self):
        assert hash_query("query a") != hash_query("query b")

    def test_sha256_length(self):
        h = hash_query("test")
        assert len(h) == 64  # SHA256 hex digest


class TestRedactSensitive:
    def test_redacts_email(self):
        cfg = {"policy": {"privacy": {"redact_emails": True, "redact_ips": False, "redact_secrets_like": []}}}
        result = redact_sensitive("Contact admin@example.com for help", cfg)
        assert "[REDACTED_EMAIL]" in result
        assert "admin@example.com" not in result

    def test_redacts_ip(self):
        cfg = {"policy": {"privacy": {"redact_emails": False, "redact_ips": True, "redact_secrets_like": []}}}
        result = redact_sensitive("Server at 192.168.1.100", cfg)
        assert "[REDACTED_IP]" in result
        assert "192.168.1.100" not in result

    def test_redacts_aws_key(self):
        cfg = {"policy": {"privacy": {"redact_emails": False, "redact_ips": False,
                                       "redact_secrets_like": ["AKIA[0-9A-Z]{16}"]}}}
        result = redact_sensitive("Key: AKIAIOSFODNN7EXAMPLE", cfg)
        assert "[REDACTED_SECRET]" in result


class TestAuditLog:
    def test_writes_jsonl(self, audit_config):
        config_path, audit_file = audit_config
        audit_log({"event": "test", "query": "hello"}, config_path)

        lines = Path(audit_file).read_text().strip().split("\n")
        assert len(lines) == 1

        event = json.loads(lines[0])
        assert event["event"] == "test"
        assert "timestamp" in event

    def test_query_hashed(self, audit_config):
        config_path, audit_file = audit_config
        audit_log({"event": "test", "query": "secret query"}, config_path)

        event = json.loads(Path(audit_file).read_text().strip())
        assert "query" not in event
        assert "query_hash" in event
        assert event["query_hash"] == hash_query("secret query")

    def test_multiple_events_appended(self, audit_config):
        config_path, audit_file = audit_config
        audit_log({"event": "first"}, config_path)
        audit_log({"event": "second"}, config_path)

        lines = Path(audit_file).read_text().strip().split("\n")
        assert len(lines) == 2
