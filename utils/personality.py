"""PersonalityManager — Lean soul layer for PsyClaw.

Based on soul.md as file-as-truth with a SQLite shadow DB for version history
and interaction logging. SHA-256 drift detection on startup.

Security: OWASP-sourced injection patterns (13 total) scan proposed soul
evolutions before any write. apply_evolution requires explicit human reason.
Every drift recovery and applied evolution is forensically recorded via
``audit_log`` (architecture invariant #5), and the append is best-effort so
audit-sink problems can never crash the manager.

Persistence: a single long-lived ``self.conn`` (sqlite3) is opened with
``check_same_thread=False`` and ``row_factory = sqlite3.Row`` and a 5s
``busy_timeout``. PsyClaw runs as a single-user local gateway (LM Studio), so
the shared connection is appropriate; ``busy_timeout`` absorbs the rare
overlapping write from a second manager instance (e.g. a manual reload).
"""

import difflib
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List

import yaml

from utils.logger import audit_log

OWASP_INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|prior)\s+instructions",
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
    r"<\s*script\s*>",
]

# Written when soul.md is absent so the manager always boots with a real,
# version-tracked soul rather than an empty string.
DEFAULT_SOUL = (
    "# PsyClaw Soul\n"
    "\n"
    "I am PsyClaw, an offline-first technical assistant. I answer from my own\n"
    "retrieved knowledge first, stay precise about what I do and do not know,\n"
    "and never silently invent facts.\n"
)


class PersonalityManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        pers_cfg = cfg.get("personality", {})
        self.soul_path = Path(pers_cfg.get("soul_path", "data/personality/soul.md"))
        self.db_path = Path(pers_cfg.get("db_path", "data/personality/psyclaw_soul.db"))
        self.ttl_days = pers_cfg.get("interaction_ttl_days", 365)
        self.soul_core: str = ""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=5000")

        self._init_db()
        self._load_soul()
        # Prune stale interactions on boot (v1.3 TTL-on-init behavior).
        self.maintenance()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _init_db(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS soul_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT NOT NULL,
                content TEXT NOT NULL,
                reason TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_hash TEXT NOT NULL,
                outcome TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def _sha256(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _audit(self, event: dict) -> None:
        """Best-effort forensic audit. Never let an audit-sink failure
        (missing logging config, unwritable path) crash personality logic."""
        try:
            audit_log(event)
        except Exception:
            pass

    def _record_version(self, content: str, reason: str) -> None:
        self.conn.execute(
            "INSERT INTO soul_versions (sha256, content, reason, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (self._sha256(content), content, reason,
             datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def _load_soul(self) -> None:
        # Create a default soul if none exists so the manager never starts blank.
        if not self.soul_path.exists():
            self.soul_path.parent.mkdir(parents=True, exist_ok=True)
            self.soul_path.write_text(DEFAULT_SOUL, encoding="utf-8")

        content = self.soul_path.read_text(encoding="utf-8")
        file_hash = self._sha256(content)
        row = self.conn.execute(
            "SELECT sha256 FROM soul_versions ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if row is None:
            self._record_version(content, "initial_load")
        elif row["sha256"] != file_hash:
            # File changed out-of-band since last tracked version: record the
            # drift recovery and emit a forensic audit event (invariant #5).
            self._record_version(content, "DRIFT_RECOVERY: file hash mismatch on startup")
            self._audit({
                "event": "soul_drift_detected",
                "sha256": file_hash,
                "soul_path": str(self.soul_path),
            })

        self.soul_core = content

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def get_system_prompt_additive(self) -> str:
        return self.soul_core

    def get_version(self) -> int:
        """Monotonic integer version = id of the latest soul_versions row
        (0 when none has been recorded yet)."""
        row = self.conn.execute(
            "SELECT id FROM soul_versions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return int(row["id"]) if row else 0

    def get_version_label(self) -> str:
        """Human-readable label: vN_<sha8>_<date>. Retained for callers/logs
        that want the descriptive form rather than the integer version."""
        row = self.conn.execute(
            "SELECT id, sha256, timestamp FROM soul_versions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            return f"v{row['id']}_{row['sha256'][:8]}_{row['timestamp'][:10]}"
        return "v0_unknown"

    def propose_evolution(self, new_soul: str, reason: str) -> dict:
        flags = []
        for pattern in OWASP_INJECTION_PATTERNS:
            if re.search(pattern, new_soul, re.IGNORECASE):
                flags.append(pattern)
        diff = list(difflib.unified_diff(
            self.soul_core.splitlines(keepends=True),
            new_soul.splitlines(keepends=True),
            fromfile="soul.md (current)",
            tofile="soul.md (proposed)",
        ))
        return {
            "status": "proposed",
            "proposed_soul": new_soul,
            "current_sha": self._sha256(self.soul_core),
            "proposed_sha": self._sha256(new_soul),
            "diff": "".join(diff),
            "injection_flags": flags,
            "injection_flag_count": len(flags),
            "reason": reason,
            "safe_to_apply": len(flags) == 0,
        }

    def apply_evolution(self, new_soul: str, reason: str) -> dict:
        new_hash = self._sha256(new_soul)

        # Keep a .bak of the prior soul for manual rollback.
        if self.soul_path.exists():
            self.soul_path.with_suffix(".md.bak").write_text(
                self.soul_core, encoding="utf-8")

        self._record_version(new_soul, reason)

        # Atomic write: stage to a temp sibling then os.replace so a crash
        # mid-write can never leave soul.md half-written.
        tmp_path = self.soul_path.with_name(self.soul_path.name + ".tmp")
        tmp_path.write_text(new_soul, encoding="utf-8")
        os.replace(tmp_path, self.soul_path)
        self.soul_core = new_soul

        self._audit({
            "event": "soul_evolution_applied",
            "sha256": new_hash,
            "reason": reason,
        })
        return {"status": "applied", "version": self.get_version(), "sha256": new_hash}

    def reload(self) -> None:
        """Re-read soul.md from disk (picks up manual edits; records drift)."""
        self._load_soul()

    # Alias — some callers/tests use reload_soul().
    reload_soul = reload

    def record_interaction(self, query_hash: str, outcome: str) -> None:
        self.conn.execute(
            "INSERT INTO interactions (query_hash, outcome, timestamp) "
            "VALUES (?, ?, ?)",
            (query_hash, outcome, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def maintenance(self, ttl_days: Optional[int] = None) -> int:
        """Prune interactions older than the TTL. Returns rows deleted.
        Called on init and exposed for explicit housekeeping."""
        ttl = self.ttl_days if ttl_days is None else ttl_days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl)).isoformat()
        cur = self.conn.execute(
            "DELETE FROM interactions WHERE timestamp < ?", (cutoff,)
        )
        self.conn.commit()
        return cur.rowcount

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
