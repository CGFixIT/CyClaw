"""Live Postgres-backend tests for PersonalityManager (the soul DB).

These exercise the real psycopg connect/execute paths in utils/personality_db.py
and utils/personality.py — the branches that need a live server and are otherwise
`# pragma: no cover`. SKIPPED unless CYCLAW_DB_URL points at a reachable Postgres,
so the default SQLite suite stays green with zero extra deps; the dedicated
`postgres-backend` CI job runs them for real.

Covers the full lifecycle on Postgres (init/version, propose+apply evolution,
SHA-256 drift recovery, TTL prune) plus the WS1 connection hardening assertions.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from utils.personality import PersonalityManager

DSN = os.environ.get("CYCLAW_DB_URL")
pytestmark = pytest.mark.skipif(
    not (DSN and DSN.startswith("postgres")),
    reason="CYCLAW_DB_URL not set to a Postgres DSN; skipping live Postgres soul-DB tests",
)


@pytest.fixture
def clean_soul_db():
    """Drop the soul tables before and after each test for isolation."""
    import psycopg

    from utils.personality_db import _harden_pg_conninfo

    def _drop():
        with psycopg.connect(_harden_pg_conninfo(DSN), autocommit=True) as conn:
            conn.execute("DROP TABLE IF EXISTS soul_versions")
            conn.execute("DROP TABLE IF EXISTS interactions")

    _drop()
    yield
    _drop()


def _cfg(tmp_path: Path, ttl_days: int = 365) -> dict:
    soul = tmp_path / "soul.md"
    soul.write_text("# Soul\nYou are a Postgres-backed test AI.", encoding="utf-8")
    return {
        "personality": {
            "soul_path": str(soul),
            "db_path": str(tmp_path / "unused.db"),  # ignored: CYCLAW_DB_URL forces Postgres
            "interaction_ttl_days": ttl_days,
            "enabled": True,
        }
    }


def test_pg_init_backend_and_version(clean_soul_db, tmp_path):
    with patch("utils.personality.audit_log"):
        pm = PersonalityManager(_cfg(tmp_path))
    assert pm._backend == "postgres"
    assert pm._ph == "%s"
    assert pm.get_version() >= 1
    assert "Postgres-backed" in pm.get_system_prompt_additive()


def test_pg_propose_apply_evolution(clean_soul_db, tmp_path):
    with patch("utils.personality.audit_log"):
        pm = PersonalityManager(_cfg(tmp_path))
        v1 = pm.get_version()
        new_soul = "# Evolved\nBe precise and Postgres-durable."
        proposal = pm.propose_evolution(new_soul, "pg test")
        assert proposal["status"] == "proposed"
        pm.apply_evolution(new_soul, "pg test")
        v2 = pm.get_version()
    assert v2 > v1
    assert "Postgres-durable" in pm.get_system_prompt_additive()


def test_pg_drift_detection(clean_soul_db, tmp_path):
    cfg = _cfg(tmp_path)
    with patch("utils.personality.audit_log"):
        pm = PersonalityManager(cfg)
        v1 = pm.get_version()
    # Tamper the soul file out-of-band, then re-init → drift recovery row written.
    Path(cfg["personality"]["soul_path"]).write_text("# Soul\nTAMPERED.", encoding="utf-8")
    with patch("utils.personality.audit_log"):
        pm2 = PersonalityManager(cfg)
        v2 = pm2.get_version()
    assert v2 > v1
    assert "TAMPERED" in pm2.get_system_prompt_additive()


def test_pg_ttl_prune(clean_soul_db, tmp_path):
    import psycopg

    from utils.personality_db import _harden_pg_conninfo

    with patch("utils.personality.audit_log"):
        pm = PersonalityManager(_cfg(tmp_path, ttl_days=1))
    # Seed an ancient interaction (timestamp is ISO-8601 TEXT; lexicographic < cutoff).
    with psycopg.connect(_harden_pg_conninfo(DSN), autocommit=True) as conn:
        conn.execute(
            "INSERT INTO interactions (query_hash, outcome, timestamp) VALUES (%s, %s, %s)",
            ("oldhash", "test", "2000-01-01T00:00:00+00:00"),
        )
        before = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
    assert before == 1
    pruned = pm.maintenance()
    assert pruned >= 1
    with psycopg.connect(_harden_pg_conninfo(DSN), autocommit=True) as conn:
        after = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
    assert after == 0


def test_pg_connection_hardening(clean_soul_db, tmp_path):
    """WS1: the soul-DB connection carries application_name + statement_timeout."""
    with patch("utils.personality.audit_log"):
        pm = PersonalityManager(_cfg(tmp_path))
    app_name = pm.conn.execute("SELECT current_setting('application_name')").fetchone()["current_setting"]
    assert app_name == "cyclaw"
    timeout = pm.conn.execute("SHOW statement_timeout").fetchone()["statement_timeout"]
    assert timeout in ("5000ms", "5s")
    # The TTL index from WS1 exists.
    idx = pm.conn.execute(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'interactions' "
        "AND indexname = 'idx_interactions_ts'"
    ).fetchone()
    assert idx is not None
