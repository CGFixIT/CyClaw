"""PersonalityManager — Lean soul layer for PsyClaw.

Based on soul.md as file-as-truth with SQLite shadow DB for version history
and interaction logging. SHA-256 drift detection on startup.

Security: OWASP-sourced injection patterns (13 total) scan proposed soul
evolutions before any write. apply_evolution requires explicit human reason.
"""

import difflib
import hashlib
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List

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

_DEFAULT_SOUL = "# Soul\n\nDefault PsyClaw soul. Replace this file with your own identity statement.\n"

# SQL stores the content's SHA-256 digest alongside a UTC timestamp as metadata —
# the hash is of *file content*, not of the time value.
_SQL_INSERT_SOUL_VERSION = (
    "INSERT INTO soul_versions (sha256, content, reason, timestamp) VALUES (?, ?, ?, ?)"  # DevSkim: ignore DS197836
)


class PersonalityManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        pers_cfg = cfg.get("personality", {})
        self.soul_path = Path(pers_cfg.get("soul_path", "data/personality/soul.md"))
        self.db_path = Path(pers_cfg.get("db_path", "data/personality/psyclaw_soul.db"))
        self.ttl_days = pers_cfg.get("interaction_ttl_days", 365)
        self.soul_core: str = ""
        self._lock = threading.Lock()
        self._init_db()
        self._load_soul()
        self.maintenance()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
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

    def _load_soul(self) -> None:
        if not self.soul_path.exists():
            self.soul_path.parent.mkdir(parents=True, exist_ok=True)
            self.soul_path.write_text(_DEFAULT_SOUL, encoding="utf-8")
            file_hash = self._sha256(_DEFAULT_SOUL)
            with self._lock:
                self.conn.execute(
                    _SQL_INSERT_SOUL_VERSION,
                    (file_hash, _DEFAULT_SOUL, "initial_default", datetime.now(timezone.utc).isoformat())
                )
                self.conn.commit()
            self.soul_core = _DEFAULT_SOUL
            return

        content = self.soul_path.read_text(encoding="utf-8")
        file_hash = self._sha256(content)
        row = self.conn.execute(
            "SELECT sha256 FROM soul_versions ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if row and row["sha256"] != file_hash:
            audit_log({
                "event": "soul_drift_detected",
                "expected": row["sha256"],
                "actual": file_hash,
                "path": str(self.soul_path),
            })
            with self._lock:
                self.conn.execute(
                    _SQL_INSERT_SOUL_VERSION,
                    (file_hash, content, "DRIFT_RECOVERY: file hash mismatch on startup",
                     datetime.now(timezone.utc).isoformat())
                )
                self.conn.commit()
        elif not row:
            with self._lock:
                self.conn.execute(
                    _SQL_INSERT_SOUL_VERSION,
                    (file_hash, content, "initial_load", datetime.now(timezone.utc).isoformat())
                )
                self.conn.commit()

        self.soul_core = content

    def get_system_prompt_additive(self) -> str:
        return self.soul_core

    def get_version(self) -> int:
        row = self.conn.execute(
            "SELECT MAX(id) FROM soul_versions"
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def propose_evolution(self, new_soul: str, reason: str) -> dict:
        flags = []
        for pattern in OWASP_INJECTION_PATTERNS:
            if re.search(pattern, new_soul, re.IGNORECASE):
                flags.append(pattern)
        diff = list(difflib.unified_diff(
            self.soul_core.splitlines(keepends=True),
            new_soul.splitlines(keepends=True),
            fromfile="soul.md (current)",
            tofile="soul.md (proposed)"
        ))
        return {
            "diff": "".join(diff),
            "injection_flags": flags,
            "injection_flag_count": len(flags),
            "reason": reason,
            "safe_to_apply": len(flags) == 0,
            "status": "proposed",
            "proposed_soul": new_soul,
            "current_sha": self._sha256(self.soul_core),
            "proposed_sha": self._sha256(new_soul),
        }

    def apply_evolution(self, new_soul: str, reason: str) -> dict:
        new_hash = self._sha256(new_soul)
        bak_path = self.soul_path.with_suffix(self.soul_path.suffix + ".bak")
        tmp_path = self.soul_path.with_suffix(self.soul_path.suffix + ".tmp")
        with self._lock:
            if self.soul_path.exists():
                bak_path.write_text(self.soul_core, encoding="utf-8")
            tmp_path.write_text(new_soul, encoding="utf-8")
            os.replace(tmp_path, self.soul_path)
            self.conn.execute(
                _SQL_INSERT_SOUL_VERSION,
                (new_hash, new_soul, reason, datetime.now(timezone.utc).isoformat())
            )
            self.conn.commit()
        self.soul_core = new_soul
        new_version = self.get_version()
        audit_log({"event": "soul_evolution_applied", "reason": reason, "version": new_version, "sha256": new_hash})
        return {"status": "applied", "version": new_version, "sha256": new_hash}

    def restore_from_backup(self) -> dict:
        bak_path = self.soul_path.with_suffix(self.soul_path.suffix + ".bak")
        if not bak_path.exists():
            raise FileNotFoundError("No .bak file found to restore from")
        backup_content = bak_path.read_text(encoding="utf-8")
        result = self.apply_evolution(backup_content, "RESTORE: reverted to previous .bak")
        audit_log({"event": "soul_restored_from_backup", "sha256": result["sha256"]})
        return result

    def reload(self) -> None:
        self._load_soul()

    reload_soul = reload

    def record_interaction(self, query_hash: str, outcome: str) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.ttl_days)).isoformat()
        with self._lock:
            self.conn.execute("DELETE FROM interactions WHERE timestamp < ?", (cutoff,))
            self.conn.execute(
                "INSERT INTO interactions (query_hash, outcome, timestamp) VALUES (?, ?, ?)",
                (query_hash, outcome, datetime.now(timezone.utc).isoformat())
            )
            self.conn.commit()

    def maintenance(self, ttl_days: int | None = None) -> int:
        if ttl_days is None:
            ttl_days = self.ttl_days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()
        with self._lock:
            cursor = self.conn.execute("DELETE FROM interactions WHERE timestamp < ?", (cutoff,))
            self.conn.commit()
            return cursor.rowcount
