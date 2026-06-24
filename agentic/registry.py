"""Governed skills registry for the agentic layer.

A JSON-backed catalog of "skills" (name + description + body) that reuses the
SAME governance pattern as soul evolution (utils/personality.py):

  - ``propose_skill`` NEVER writes. It returns a diff plus *advisory* injection
    flags so a human can review the change.
  - ``apply_skill`` ENFORCES the injection gate at the write boundary, requires a
    non-empty human ``reason``, writes atomically (tmp + os.replace), and records
    a sha256-versioned history entry.

The injection scanner is the SAME union the soul scanner uses -- the curated
``policy.prompt_filter.banned_patterns`` from config.yaml unioned with the OWASP
baseline -- so a skill body can never smuggle in instructions that the query path
would reject. This is the soul-governance invariant applied to a new surface.

Never imported by gate.py / graph.py / mcp_hybrid_server.py.

Wired with governance_score in feature/CyClaw-Agent for agentic visibility.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

from agentic.config import AgenticConfig
from utils.errors import PromptInjectionError, SkillRegistryError
from utils.logger import audit_log

# Reuse the soul scanner's OWASP baseline so the two never drift.
from utils.personality import OWASP_INJECTION_PATTERNS


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


class SkillRegistry:
    """File-as-truth skills catalog with propose/apply governance.

    governance_score(name) added in feature/CyClaw-Agent to give the agentic
    layer a 0-100 signal of how well-governed a skill is (low injection flags,
    good structure, etc.). Used by verification-specialist and registry tools.
    """

    def __init__(self, cfg: dict, agentic_cfg: AgenticConfig | None = None):
        self.cfg = cfg
        ac = agentic_cfg or AgenticConfig()
        self.registry_path = Path(ac.registry_path)
        self._lock = threading.Lock()
        self._injection_patterns = self._build_injection_patterns()
        self._data = self._load()

    # --- persistence ------------------------------------------------------

    def _empty(self) -> dict:
        return {"version": 0, "updated": None, "skills": {}, "history": []}

    def _load(self) -> dict:
        if not self.registry_path.exists():
            return self._empty()
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillRegistryError(
                f"Could not read skills registry: {exc}",
                details={"path": str(self.registry_path)},
            ) from exc
        if not isinstance(data, dict) or "skills" not in data:
            raise SkillRegistryError(
                "Skills registry is malformed (missing 'skills')",
                details={"path": str(self.registry_path)},
            )
        return data

    def _atomic_write(self, data: dict) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.registry_path.with_suffix(self.registry_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, self.registry_path)

    # --- scanning (mirrors PersonalityManager) ----------------------------

    def _build_injection_patterns(self) -> list[tuple]:
        sources: list[str] = list(OWASP_INJECTION_PATTERNS)
        pf = (self.cfg.get("policy") or {}).get("prompt_filter") or {}
        for p in (pf.get("banned_patterns") or []):
            if p not in sources:
                sources.append(p)
        compiled: list[tuple] = []
        for p in sources:
            try:
                compiled.append((p, re.compile(p, re.IGNORECASE)))
            except re.error:
                continue
        return compiled

    def _scan_injection(self, text: str) -> list[str]:
        return [src for src, pat in self._injection_patterns if pat.search(text)]

    @staticmethod
    def _sha256(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical(spec: dict) -> str:
        """Stable string for hashing/scanning a skill spec."""
        return f"{spec.get('name', '')}\n{spec.get('description', '')}\n{spec.get('body', '')}"

    @staticmethod
    def _validate_spec(spec: dict) -> None:
        for key in ("name", "description", "body"):
            if not isinstance(spec.get(key), str) or not spec.get(key, "").strip():
                raise SkillRegistryError(
                    f"skill spec field {key!r} must be a non-empty string",
                    details={"field": key},
                )
        if not re.match(r"^[A-Za-z0-9_.-]+$", spec["name"]):
            raise SkillRegistryError(
                f"skill name must match ^[A-Za-z0-9_.-]+$, got {spec['name']!r}",
                details={"name": spec["name"]},
            )

    # --- read -------------------------------------------------------------

    def list_skills(self) -> list[str]:
        return sorted(self._data.get("skills", {}).keys())

    def get_skill(self, name: str) -> dict | None:
        return self._data.get("skills", {}).get(name)

    def version(self) -> int:
        return int(self._data.get("version", 0))

    # NEW: governance_score for agentic visibility and verification-specialist
    def governance_score(self, name: str) -> int:
        """Return 0-100 governance score for a *registered* skill.

        Higher = better governed (low injection risk, good structure).
        Used by agentic tools and verification-specialist skill.
        """
        skill = self.get_skill(name)
        if not skill:
            return 0
        return self._score_spec(skill)

    def _score_spec(self, spec: dict) -> int:
        """Score an arbitrary skill spec (stored OR proposed) on the 0-100 scale.

        Factored out of :meth:`governance_score` so :meth:`propose_skill` can
        score the *proposed* body a human is about to apply, rather than the
        version already on disk — which is 0 for a brand-new skill and the
        stale body for an update.
        """
        canonical = self._canonical(spec)
        flags = self._scan_injection(canonical)
        # Heavy penalty for injection patterns (core invariant)
        penalty = min(len(flags) * 25, 80)
        score = 100 - penalty
        # Bonus for decent description (helps human review)
        if spec.get("description") and len(spec.get("description", "")) > 30:
            score += 8
        # Bonus for non-trivial body
        if spec.get("body") and len(spec.get("body", "")) > 100:
            score += 5
        return max(0, min(100, int(score)))

    # --- propose / apply (mirrors personality) ----------------------------

    def propose_skill(self, spec: dict, reason: str) -> dict:
        """Preview a skill add/update. NEVER writes; flags are advisory only.

        Enforcement lives at the write boundary in :meth:`apply_skill`.
        """
        self._validate_spec(spec)
        canonical = self._canonical(spec)
        flags = self._scan_injection(canonical)
        existing = self.get_skill(spec["name"]) or {}
        diff = list(difflib.unified_diff(
            (existing.get("body", "") or "").splitlines(keepends=True),
            spec["body"].splitlines(keepends=True),
            fromfile=f"{spec['name']} (current)",
            tofile=f"{spec['name']} (proposed)",
        ))
        return {
            "status": "proposed",
            "name": spec["name"],
            "diff": "".join(diff),
            "injection_flags": flags,
            "injection_flag_count": len(flags),
            "safe_to_apply": len(flags) == 0,
            "reason": reason,
            "proposed_sha": self._sha256(canonical),
            "is_update": bool(existing),
            # Score the PROPOSED spec (what the human is about to apply), not the
            # version on disk. The old form returned the stored skill's score for
            # an update (stale body) and a hardcoded 0 for a brand-new skill,
            # making the preview's governance signal misleading.
            "governance_score": self._score_spec(spec),
        }

    def apply_skill(self, spec: dict, reason: str, *, scan: bool = True) -> dict:
        """Atomically add/update a skill, enforcing the injection gate.

        Requires a non-empty human ``reason``. With ``scan=True`` (default) a skill
        whose canonical text contains injection patterns raises
        ``PromptInjectionError`` before any write -- closing the skill-poisoning
        vector. The write is atomic (tmp + os.replace).
        """
        self._validate_spec(spec)
        if not (isinstance(reason, str) and reason.strip()):
            raise SkillRegistryError(
                "apply_skill requires a non-empty human reason",
                details={"name": spec.get("name")},
            )

        canonical = self._canonical(spec)
        if scan:
            flags = self._scan_injection(canonical)
            if flags:
                audit_log({
                    "event": "agentic_skill_injection_blocked",
                    "name": spec["name"],
                    "reason": reason,
                    "injection_flag_count": len(flags),
                })
                raise PromptInjectionError(
                    "Proposed skill contains injection patterns; refusing to apply",
                    details={"injection_flags": flags, "name": spec["name"]},
                )

        new_sha = self._sha256(canonical)
        ts = _utcnow()
        with self._lock:
            data = dict(self._data)
            skills = dict(data.get("skills", {}))
            history = list(data.get("history", []))
            skills[spec["name"]] = {
                "name": spec["name"],
                "description": spec["description"],
                "body": spec["body"],
                "sha256": new_sha,
                "reason": reason,
                "updated": ts,
            }
            new_version = int(data.get("version", 0)) + 1
            history.append({
                "version": new_version,
                "name": spec["name"],
                "sha256": new_sha,
                "reason": reason,
                "timestamp": ts,
            })
            data.update({"version": new_version, "updated": ts,
                         "skills": skills, "history": history})
            self._atomic_write(data)
            self._data = data

        audit_log({
            "event": "agentic_skill_applied",
            "name": spec["name"],
            "reason": reason,
            "version": new_version,
            "sha256": new_sha,
        })
        return {"status": "applied", "name": spec["name"],
                "version": new_version, "sha256": new_sha, "governance_score": self.governance_score(spec["name"]) }


__all__ = ["SkillRegistry"]
