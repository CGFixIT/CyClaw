"""Unit tests for audit logging — hashing, redaction, JSONL output."""

import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest
import yaml

from utils.logger import hash_query, redact_sensitive, audit_log, reset_config_cache


def test_hash_query_is_sha256():
    result = hash_query("test query")
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)

def test_hash_query_is_deterministic():
    assert hash_query("hello") == hash_query("hello")

def test_hash_query_different_inputs_differ():
    assert hash_query("query1") != hash_query("query2")

def test_redact_email(test_config):
    cfg, _ = test_config
    result = redact_sensitive("Contact user@example.com for help", cfg)
    assert "user@example.com" not in result
    assert "[REDACTED_EMAIL]" in result

def test_redact_ip(test_config):
    cfg, _ = test_config
    result = redact_sensitive("Server at 192.168.1.100 is down", cfg)
    assert "192.168.1.100" not in result
    assert "[REDACTED_IP]" in result

def test_redact_aws_key(test_config):
    cfg, _ = test_config
    result = redact_sensitive("Key: AKIAIOSFODNN7EXAMPLE", cfg)
    assert "AKIAIOSFODNN7EXAMPLE" not in result

def test_audit_log_writes_jsonl(test_config, tmp_path):
    cfg, config_path = test_config
    reset_config_cache()
    audit_log({"event": "test_event", "detail": "hello"}, config_path=config_path)
    audit_file = Path(cfg["logging"]["audit_file"])
    assert audit_file.exists()
    lines = audit_file.read_text().strip().split("\n")
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event"] == "test_event"
    assert "timestamp" in event

def test_audit_log_hashes_query(test_config):
    cfg, config_path = test_config
    reset_config_cache()
    audit_log({"event": "query", "query": "what is rag?"}, config_path=config_path)
    audit_file = Path(cfg["logging"]["audit_file"])
    lines = audit_file.read_text().strip().split("\n")
    event = json.loads(lines[-1])
    assert "query" not in event
    assert "query_hash" in event
    assert len(event["query_hash"]) == 64
