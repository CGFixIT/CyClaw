# ============================================================================
# BUILD-ALIGNMENT NOTE (2026-06-13): Targets a FUTURE PsyClaw build (pending
# Dropbox sync). Soul propose/apply-evolution and TTL-maintenance behaviors
# here do not all match the current pushed implementation and will fail against
# HEAD until that build is pushed. Expected, not a regression. Do not 'fix'.
# ============================================================================
#!/usr/bin/env python
"""Unit tests for v1.3 changes in utils/personality.py"""

import os
import sys
import tempfile
import shutil
import hashlib
from pathlib import Path
from unittest.mock import patch

# Add project to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.personality import PersonalityManager


def test_personality_init_and_version():
    """Test basic init, version tracking, and soul load."""
    with tempfile.TemporaryDirectory() as tmp:
        soul_path = Path(tmp) / "soul.md"
        db_path = Path(tmp) / "test_soul.db"

        # Create initial soul
        initial_soul = "# Test Soul\nYou are a test AI."
        soul_path.write_text(initial_soul)

        cfg = {
            "personality": {
                "soul_path": str(soul_path),
                "db_path": str(db_path),
                "interaction_ttl_days": 90,
                "enabled": True
            }
        }

        with patch("utils.personality.audit_log"):
            pm = PersonalityManager(cfg)
        assert pm.get_version() >= 1, "Version should be at least 1 after init"
        assert "Test Soul" in pm.get_system_prompt_additive()
        print("✓ test_personality_init_and_version passed")

def test_propose_apply_evolution():
    """Test propose and apply with atomic write (v1.3)."""
    with tempfile.TemporaryDirectory() as tmp:
        soul_path = Path(tmp) / "soul.md"
        db_path = Path(tmp) / "test_soul.db"

        initial = "# Initial\nBe helpful."
        soul_path.write_text(initial)

        cfg = {"personality": {"soul_path": str(soul_path), "db_path": str(db_path), "interaction_ttl_days": 30}}

        with patch("utils.personality.audit_log"):
            pm = PersonalityManager(cfg)
        v1 = pm.get_version()

        new_soul = "# Evolved\nBe brutally honest."
        proposal = pm.propose_evolution(new_soul, "test reason")
        assert "proposed" in proposal["status"]
        assert proposal["current_sha"] != proposal["proposed_sha"]

        with patch("utils.personality.audit_log"):
            pm.apply_evolution(new_soul, "test reason")
        v2 = pm.get_version()
        assert v2 > v1, "Version should increment"
        assert "brutally honest" in pm.get_system_prompt_additive()

        # Verify atomic: no .tmp left
        assert not (soul_path.with_suffix(".tmp")).exists()
        print("✓ test_propose_apply_evolution passed")

def test_drift_detection():
    """Test SHA-256 drift detection and auto-recovery (v1.3)."""
    with tempfile.TemporaryDirectory() as tmp:
        soul_path = Path(tmp) / "soul.md"
        db_path = Path(tmp) / "test_soul.db"

        initial = "# Drift Test\nOriginal."
        soul_path.write_text(initial)

        cfg = {"personality": {"soul_path": str(soul_path), "db_path": str(db_path), "interaction_ttl_days": 30}}

        with patch("utils.personality.audit_log"):
            pm = PersonalityManager(cfg)
        v1 = pm.get_version()

        # Simulate external tamper / manual edit
        tampered = "# Drift Test\nTAMPERED CONTENT!"
        soul_path.write_text(tampered)

        # Re-init should detect drift, log, and recover
        with patch("utils.personality.audit_log"):
            pm2 = PersonalityManager(cfg)
        v2 = pm2.get_version()
        assert v2 > v1, "Drift should trigger new version"
        # Content should be the tampered one now (as recovery)
        assert "TAMPERED" in pm2.get_system_prompt_additive()
        print("✓ test_drift_detection passed")

def test_ttl_maintenance():
    """Test interaction TTL prune on init (v1.3)."""
    with tempfile.TemporaryDirectory() as tmp:
        soul_path = Path(tmp) / "soul.md"
        db_path = Path(tmp) / "test_soul.db"

        soul_path.write_text("# TTL Test")

        cfg = {"personality": {"soul_path": str(soul_path), "db_path": str(db_path), "interaction_ttl_days": 1}}

        with patch("utils.personality.audit_log"):
            pm = PersonalityManager(cfg)
        # Manually insert old interaction
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO interactions (timestamp, query_hash, outcome) VALUES (?, ?, ?)",
                     ("2020-01-01T00:00:00+00:00", "oldhash", "test"))
        conn.commit()
        conn.close()

        # Re-init should prune
        with patch("utils.personality.audit_log"):
            pm2 = PersonalityManager(cfg)
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
        conn.close()
        assert count == 0, "Old interaction should be pruned"
        print("✓ test_ttl_maintenance passed")

if __name__ == "__main__":
    print("Running PersonalityManager v1.3 unit tests...")
    test_personality_init_and_version()
    test_propose_apply_evolution()
    test_drift_detection()
    test_ttl_maintenance()
    print("\n✅ All personality changes verified!")
