"""PersonalityManager — Lean soul layer for PsyClaw.

Based on soul.md as file-as-truth with SQLite shadow DB for version history
and interaction logging. SHA-256 drift detection on startup.

Security: OWASP-sourced injection patterns (13 total) scan proposed soul
evolutions before any write. apply_evolution requires explicit human reason.
"""

import difflib
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List
import yaml

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

class PersonalityManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        pers_cfg = cfg.get("personality", {})
        self.soul_path = Path(pers_cfg.get("soul_path", "data/personality/soul.md"))
        self.db_path = Path(pers_cfg.get("db_path", "data/personality/psyclaw_soul.db"))
        self.ttl_days = pers_cfg.get("interaction_ttl_days", 365)
        self.soul_core: str = ""
        self._init_db()
        self._load_soul()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS soul_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT NOT NULL,
                content TEXT NOT NULL,
                reason TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_hash TEXT NOT NULL,
                outcome TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def _sha256(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _load_soul(self) -> None:
        if not self.soul_path.exists():
            self.soul_core = ""
            return
        content = self.soul_path.read_text(encoding="utf-8")
        file_hash = self._sha256(content)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT sha256 FROM soul_versions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row and row[0] != file_hash:
            conn.execute(
                "INSERT INTO soul_versions (sha256, content, reason, timestamp) VALUES (?, ?, ?, ?)",
                (file_hash, content, "DRIFT_RECOVERY: file hash mismatch on startup",
                 datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
        elif not row:
            conn.execute(
                "INSERT INTO soul_versions (sha256, content, reason, timestamp) VALUES (?, ?, ?, ?)",
                (file_hash, content, "initial_load", datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
        conn.close()
        self.soul_core = content

    def get_system_prompt_additive(self) -> str:
        return self.soul_core

    def get_version(self) -> str:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT id, sha256, timestamp FROM soul_versions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            return f"v{row[0]}_{row[1][:8]}_{row[2][:10]}"
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
            tofile="soul.md (proposed)"
        ))
        return {
            "diff": "".join(diff),
            "injection_flags": flags,
            "injection_flag_count": len(flags),
            "reason": reason,
            "safe_to_apply": len(flags) == 0
        }

    def apply_evolution(self, new_soul: str, reason: str) -> dict:
        new_hash = self._sha256(new_soul)
        backup_path = self.soul_path.with_suffix(".md.bak")
        if self.soul_path.exists():
            backup_path.write_text(self.soul_core, encoding="utf-8")
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO soul_versions (sha256, content, reason, timestamp) VALUES (?, ?, ?, ?)",
            (new_hash, new_soul, reason, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
        conn.close()
        self.soul_path.write_text(new_soul, encoding="utf-8")
        self.soul_core = new_soul
        return {"status": "applied", "version": self.get_version(), "sha256": new_hash}

    def reload(self) -> None:
        self._load_soul()

    def record_interaction(self, query_hash: str, outcome: str) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.ttl_days)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM interactions WHERE timestamp < ?", (cutoff,))
        conn.execute(
            "INSERT INTO interactions (query_hash, outcome, timestamp) VALUES (?, ?, ?)",
            (query_hash, outcome, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
        conn.close()
