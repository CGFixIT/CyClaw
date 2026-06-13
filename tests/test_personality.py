# ============================================================================
# BUILD-ALIGNMENT NOTE (2026-06-13): Some tests below target a FUTURE PsyClaw
# build not yet pushed to GitHub (pending Dropbox sync of the local working
# tree). They reference APIs absent from the current pushed implementation and
# will ERROR/FAIL against HEAD until that build lands — expected, not a bug:
#   * pm.conn                         (no persistent conn attr at HEAD)
#   * pm.reload_soul()                (HEAD exposes reload())
#   * pm.maintenance(...)             (no maintenance() method at HEAD yet)
#   * patch('utils.personality.audit_log')  (personality.py doesn't import audit_log at HEAD)
# Do NOT 'fix' by downgrading these tests to the older pushed API.
# ============================================================================
"""Tests for PersonalityManager — soul.md persistent personality layer.

Run: pytest tests/test_personality.py -v
"""

import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

# Minimal config for testing
TEST_CONFIG = {
    "personality": {
        "soul_path": None,  # Set per test
        "db_path": None,    # Set per test
    },
    "logging": {
        "audit_file": None,  # Set per test
        "audit_fields": {"include_query_hash": True},
    },
    "policy": {"privacy": {}},
}


@pytest.fixture
def tmp_paths(tmp_path):
    """Create temp paths for soul.md, DB, and audit log."""
    soul = tmp_path / "personality" / "soul.md"
    db = tmp_path / "personality" / "psyclaw_soul.db"
    audit = tmp_path / "logs" / "audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    return soul, db, audit


@pytest.fixture
def cfg(tmp_paths):
    """Build test config with temp paths."""
    soul, db, audit = tmp_paths
    config = TEST_CONFIG.copy()
    config["personality"] = {
        "soul_path": str(soul),
        "db_path": str(db),
    }
    config["logging"] = {
        "audit_file": str(audit),
        "audit_fields": {"include_query_hash": True},
    }
    config["policy"] = {"privacy": {}}
    return config


class TestPersonalityManager:
    """Core PersonalityManager tests."""

    def test_creates_default_soul_when_missing(self, cfg, tmp_paths):
        """If no soul.md exists, PM creates a minimal fallback."""
        soul_path, _, _ = tmp_paths

        # Mock audit_log to avoid config issues
        with patch("utils.personality.audit_log"):
            from utils.personality import PersonalityManager
            pm = PersonalityManager(cfg)

        assert soul_path.exists()
        content = soul_path.read_text()
        assert "PsyClaw" in content
        assert pm.soul_core == content

    def test_loads_existing_soul(self, cfg, tmp_paths):
        """If soul.md exists, PM loads it and seeds DB."""
        soul_path, _, _ = tmp_paths
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        soul_path.write_text("# Custom Soul\nI am custom.", encoding="utf-8")

        with patch("utils.personality.audit_log"):
            from utils.personality import PersonalityManager
            pm = PersonalityManager(cfg)

        assert pm.soul_core == "# Custom Soul\nI am custom."
        assert pm.get_version() == 1

    def test_get_system_prompt_additive(self, cfg, tmp_paths):
        """get_system_prompt_additive returns current soul text."""
        soul_path, _, _ = tmp_paths
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        soul_path.write_text("# Test Soul", encoding="utf-8")

        with patch("utils.personality.audit_log"):
            from utils.personality import PersonalityManager
            pm = PersonalityManager(cfg)

        assert pm.get_system_prompt_additive() == "# Test Soul"

    def test_propose_evolution_returns_proposal(self, cfg, tmp_paths):
        """propose_evolution returns dict without modifying soul."""
        soul_path, _, _ = tmp_paths
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        soul_path.write_text("# Original", encoding="utf-8")

        with patch("utils.personality.audit_log"):
            from utils.personality import PersonalityManager
            pm = PersonalityManager(cfg)

        proposal = pm.propose_evolution("# New Soul", "testing")
        assert proposal["status"] == "proposed"
        assert proposal["proposed_soul"] == "# New Soul"
        # Original should be unchanged
        assert pm.soul_core == "# Original"

    def test_apply_evolution_writes_file_and_db(self, cfg, tmp_paths):
        """apply_evolution updates disk file, DB, and in-memory state."""
        soul_path, _, _ = tmp_paths
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        soul_path.write_text("# V1", encoding="utf-8")

        with patch("utils.personality.audit_log"):
            from utils.personality import PersonalityManager
            pm = PersonalityManager(cfg)

        assert pm.get_version() == 1

        with patch("utils.personality.audit_log"):
            pm.apply_evolution("# V2", "test upgrade")

        assert pm.soul_core == "# V2"
        assert soul_path.read_text() == "# V2"
        assert pm.get_version() == 2

    def test_reload_soul_picks_up_manual_edits(self, cfg, tmp_paths):
        """reload_soul re-reads the file after external modification."""
        soul_path, _, _ = tmp_paths
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        soul_path.write_text("# Before Edit", encoding="utf-8")

        with patch("utils.personality.audit_log"):
            from utils.personality import PersonalityManager
            pm = PersonalityManager(cfg)

        assert pm.soul_core == "# Before Edit"

        # Simulate manual edit
        soul_path.write_text("# After Edit", encoding="utf-8")
        pm.reload_soul()
        assert pm.soul_core == "# After Edit"

    def test_record_interaction(self, cfg, tmp_paths):
        """record_interaction inserts row into interactions table."""
        soul_path, _, _ = tmp_paths
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        soul_path.write_text("# Test", encoding="utf-8")

        with patch("utils.personality.audit_log"):
            from utils.personality import PersonalityManager
            pm = PersonalityManager(cfg)
            pm.record_interaction("abc123", "local")

        row = pm.conn.execute(
            "SELECT * FROM interactions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row["query_hash"] == "abc123"
        assert row["outcome"] == "local"

    def test_maintenance_prunes_old_interactions(self, cfg, tmp_paths):
        """maintenance() removes interactions older than TTL."""
        soul_path, _, _ = tmp_paths
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        soul_path.write_text("# Test", encoding="utf-8")

        with patch("utils.personality.audit_log"):
            from utils.personality import PersonalityManager
            pm = PersonalityManager(cfg)

        # Insert an old interaction
        pm.conn.execute(
            "INSERT INTO interactions (timestamp, query_hash, outcome) "
            "VALUES (datetime('now', '-100 days'), 'old', 'local')"
        )
        pm.conn.execute(
            "INSERT INTO interactions (timestamp, query_hash, outcome) "
            "VALUES (datetime('now'), 'new', 'local')"
        )
        pm.conn.commit()

        pm.maintenance(ttl_days=90)

        rows = pm.conn.execute("SELECT * FROM interactions").fetchall()
        assert len(rows) == 1
        assert rows[0]["query_hash"] == "new"
