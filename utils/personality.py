"""PersonalityManager — Lean soul layer for CyClaw.

Based on soul.md as file-as-truth with a shadow DB for version history
and interaction logging. SHA-256 drift detection on startup.

Database backend: SQLite by default (zero-config, offline-first). Switch to
Postgres by setting CYCLAW_DB_URL=postgresql://... or personality.database_url
in config.yaml. See utils/personality_db.py for the connection shim.

Security: proposed soul evolutions are scanned before any write using the SAME
banned-pattern set the query path uses (config.yaml policy.prompt_filter), unioned
with a legacy OWASP baseline — so the soul (prepended to every LLM system prompt)
is no longer guarded by a weaker list than user queries. apply_evolution requires
an explicit human reason.
"""

import difflib
import hashlib
import os
import re
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List

from utils import personality_db
from utils.errors import PromptInjectionError
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

_DEFAULT_SOUL = "# Soul\n\nDefault CyClaw soul. Replace this file with your own identity statement.\n"


class PersonalityManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        pers_cfg = cfg.get("personality", {})
        self.soul_path = Path(pers_cfg.get("soul_path", "data/personality/soul.md"))
        self.db_path = Path(pers_cfg.get("db_path", "data/personality/cyclaw_soul.db"))
        self.ttl_days = pers_cfg.get("interaction_ttl_days", 365)
        # Amortize TTL pruning: sweep once per this many inserts instead of on
        # every record_interaction() call (see record_interaction for rationale).
        self._prune_every = pers_cfg.get("interaction_prune_every", 100)
        self._inserts_since_prune = 0
        self.soul_core: str = ""
        # Compile the injection scanner once: config banned_patterns ∪ OWASP.
        self._injection_patterns = self._build_injection_patterns()
        self._lock = threading.Lock()
        self._init_db()
        self._load_soul()
        self.maintenance()

    def _init_db(self) -> None:
        pers_cfg = self.cfg.get("personality", {})
        self.conn, self._ph, self._backend = personality_db.connect(self.db_path, pers_cfg)
        # Build parameterized SQL templates for this backend.
        # sha256 stores a hash of soul file *content*, not of the timestamp — the two are independent columns.
        self._sql_insert_soul = (
            f"INSERT INTO soul_versions (sha256, content, reason, timestamp)"  # DevSkim: ignore DS197836
            f" VALUES ({self._ph}, {self._ph}, {self._ph}, {self._ph})"
        )
        self._sql_insert_interaction = (
            f"INSERT INTO interactions (query_hash, outcome, timestamp)"
            f" VALUES ({self._ph}, {self._ph}, {self._ph})"
        )
        self._sql_delete_old_interactions = (
            f"DELETE FROM interactions WHERE timestamp < {self._ph}"
        )
        self.conn.execute(personality_db.ddl_soul_versions(self._backend))
        self.conn.execute(personality_db.ddl_interactions(self._backend))
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
                    self._sql_insert_soul,
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
                    self._sql_insert_soul,
                    (file_hash, content, "DRIFT_RECOVERY: file hash mismatch on startup",
                     datetime.now(timezone.utc).isoformat())
                )
                self.conn.commit()
        elif not row:
            with self._lock:
                self.conn.execute(
                    self._sql_insert_soul,
                    (file_hash, content, "initial_load", datetime.now(timezone.utc).isoformat())
                )
                self.conn.commit()

        self.soul_core = content

    def get_system_prompt_additive(self) -> str:
        return self.soul_core

    def get_version(self) -> int:
        row = self.conn.execute(
            "SELECT MAX(id) AS max_id FROM soul_versions"
        ).fetchone()
        return int(row["max_id"]) if row and row["max_id"] is not None else 0

    def _build_injection_patterns(self) -> List[tuple]:
        """Compile the soul scanner from the query-path filter ∪ the OWASP baseline.

        The query path (utils.sanitizer) filters input against the 31 curated
        ``policy.prompt_filter.banned_patterns`` in config.yaml — including the
        Memory/Persistence category that is "HIGH PRIORITY for RAG + soul". The
        soul scanner previously used only a hardcoded 13-pattern OWASP list, so a
        memory-poisoning proposal (e.g. "update your soul", "core instruction,
        never forget") passed the soul scan and was written to soul.md. Sourcing
        from the same config set keeps the two from drifting; the OWASP list is
        retained as a floor so a minimal/absent config still scans (never zero
        patterns). Returns ``(source_string, compiled)`` pairs; invalid regexes
        are skipped rather than crashing the manager.
        """
        sources: List[str] = list(OWASP_INJECTION_PATTERNS)
        pf = (self.cfg.get("policy") or {}).get("prompt_filter") or {}
        for p in (pf.get("banned_patterns") or []):
            if p not in sources:
                sources.append(p)
        compiled: List[tuple] = []
        for p in sources:
            try:
                compiled.append((p, re.compile(p, re.IGNORECASE)))
            except re.error:
                continue
        return compiled

    def _scan_injection(self, text: str) -> List[str]:
        """Return every banned pattern (config ∪ OWASP) that matches ``text``."""
        return [src for src, pat in self._injection_patterns if pat.search(text)]

    def propose_evolution(self, new_soul: str, reason: str) -> dict:
        """Preview a proposed soul change: compute the diff + advisory injection flags.

        This method NEVER writes. ``injection_flags`` / ``safe_to_apply`` are an
        advisory signal surfaced for the human reviewing the proposal. Enforcement
        does not live here — it lives at the write boundary in
        :meth:`apply_evolution`, which re-runs the scan and refuses flagged content.
        """
        flags = self._scan_injection(new_soul)
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

    def apply_evolution(self, new_soul: str, reason: str, *, scan: bool = True) -> dict:
        """Atomically write a new soul, enforcing the injection gate at the boundary.

        Authority to change the soul is human-gated: an explicit ``reason`` string
        is required and there is no autonomous/graph path here. On top of that, the
        injection scan is ENFORCED at the write boundary (``scan=True``, default):
        a proposed soul containing OWASP injection patterns raises
        ``PromptInjectionError`` before any file/DB write, closing the
        soul-poisoning vector (a flagged soul would otherwise be prepended to every
        LLM system prompt). The trusted internal restore path
        (:meth:`restore_from_backup`, re-applying a previously vetted ``.bak``)
        passes ``scan=False``. The write itself is atomic (``tmp`` + ``os.replace``)
        so a crash cannot leave a half-written ``soul.md``.
        """
        # Enforce the injection gate at the write boundary. propose_evolution()
        # only *flags* patterns and is advisory; without this check apply_evolution()
        # would persist any payload — including "ignore previous instructions" — straight
        # to soul.md, which is then prepended to every LLM system prompt. Trusted internal
        # callers that re-apply previously vetted content (restore_from_backup) pass scan=False.
        if scan:
            flags = self._scan_injection(new_soul)
            if flags:
                audit_log({"event": "soul_apply_injection_blocked",
                           "reason": reason, "injection_flag_count": len(flags)})
                raise PromptInjectionError(
                    "Proposed soul contains injection patterns; refusing to apply",
                    details={"injection_flags": flags, "injection_flag_count": len(flags)},
                )
        new_hash = self._sha256(new_soul)
        bak_path = self.soul_path.with_suffix(self.soul_path.suffix + ".bak")
        tmp_path = self.soul_path.with_suffix(self.soul_path.suffix + ".tmp")
        with self._lock:
            if self.soul_path.exists():
                bak_path.write_text(self.soul_core, encoding="utf-8")
            tmp_path.write_text(new_soul, encoding="utf-8")
            os.replace(tmp_path, self.soul_path)
            self.conn.execute(
                self._sql_insert_soul,
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
        # Non-blocking re-scan (PR #99 #7): the restore path intentionally uses
        # scan=False (the .bak is previously-vetted content, and
        # test_scan_false_bypass_for_trusted_restore documents that contract).
        # We still scan and audit-log any match — so if a .bak ever trips the
        # now-widened pattern set it is visible — without refusing the restore.
        restore_flags = self._scan_injection(backup_content)
        if restore_flags:
            audit_log({"event": "soul_restore_scan_flags",
                       "injection_flag_count": len(restore_flags)})
        result = self.apply_evolution(backup_content, "RESTORE: reverted to previous .bak", scan=False)
        audit_log({"event": "soul_restored_from_backup", "sha256": result["sha256"]})
        return result

    def reload(self) -> None:
        self._load_soul()

    reload_soul = reload

    def record_interaction(self, query_hash: str, outcome: str) -> None:
        with self._lock:
            self.conn.execute(
                self._sql_insert_interaction,
                (query_hash, outcome, datetime.now(timezone.utc).isoformat())
            )
            # Amortize the TTL prune. The previous code ran a full
            # `DELETE FROM interactions WHERE timestamp < cutoff` on *every*
            # insert -- and this runs on the hot audit path
            # (audit_logger_node -> record_interaction per query). With the
            # default 365-day TTL that DELETE scans the table and matches
            # nothing on virtually every call, so it was pure write
            # amplification under the lock. maintenance() already prunes on
            # __init__, and now we also sweep once per `_prune_every` inserts
            # (mirroring utils/ratelimit.py's periodic _sweep) so a
            # long-running server still bounds the table without paying the
            # DELETE cost on each request.
            self._inserts_since_prune += 1
            if self._inserts_since_prune >= self._prune_every:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=self.ttl_days)).isoformat()
                self.conn.execute(self._sql_delete_old_interactions, (cutoff,))
                self._inserts_since_prune = 0
            self.conn.commit()

    def maintenance(self, ttl_days: int | None = None) -> int:
        if ttl_days is None:
            ttl_days = self.ttl_days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()
        with self._lock:
            cursor = self.conn.execute(self._sql_delete_old_interactions, (cutoff,))
            self.conn.commit()
            return cursor.rowcount
