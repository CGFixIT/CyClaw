# PsyClaw — Security Audit Report

**Date:** 2026-06-09
**Scope:** Full repository review of `CGFixIT/PsyClaw` @ `origin/main` (`4bbe1d9`)
**Excluded by request:** the known langgraph/langchain CVE (being handled via the dependabot bump to `langgraph 1.0.10rc1` / `langchain-core 1.3.3`).
**Method:** line-by-line read of every source, config, workflow, static asset, test, doc, and env file; secret pattern scan; git-history check.

---

## Verdict

**The codebase is well-built defensively.** No leaked secrets, no reachable injection / SSRF / XSS, no dangerous workflow patterns. Your deletion of `ci.yml` and `fortify.yml` retired most of the original Actions findings. What remains is modest hardening — and nearly all of it is gated by the fact that the gateway binds to `127.0.0.1` only.

Overall risk posture: **LOW** for the stated personal/home-lab use; a couple of items would escalate to MEDIUM/HIGH **only if the service were ever exposed beyond localhost**.

---

## Strengths confirmed (not issues)

| Area | Evidence |
|---|---|
| Telemetry kill-switch at import | `gate.py:25-49` + `psyclaw_telemetry_kill.env` |
| Raw query text never logged (SHA-256 hashed) + email/IP/secret redaction | `utils/logger.py` |
| HTTP 500 error sanitization (Bearer/api-key/AWS/GitHub/Slack + live env values) | `gate.py:86-108` |
| Per-IP rate limiting on `/query` | `gate.py:78-84` |
| Consistent output escaping — no XSS | `static/terminal.html` (`escHtml`/`textContent`), `static/extractor.html` (`escapeHtml`) |
| Parameterized SQL; `yaml.safe_load` throughout | `utils/personality.py`, all loaders |
| Retrieved context labeled untrusted, separated from identity | `graph.py:155-160` |
| MCP server stdio-only, `sampling: None` — no network, no LLM path, no SSRF | `mcp_hybrid_server.py` |
| Outbound URLs come from config, never user input | `llm/client.py`, `utils/health.py` |
| `127.0.0.1` bind; sound `.gitignore`; no committed secrets | `config.yaml`, `.gitignore` |
| Remaining workflow `codeql.yml` is clean | least-priv `permissions:`, `pull_request` (not `_target`) |

---

## Findings

### F1 — Soul-evolution write path: unauthenticated + advisory-only enforcement — MEDIUM
*(LOW in pure-localhost use; HIGH if ever exposed)*

- `/soul`, `/soul/propose`, `/soul/apply`, `/soul/reload` (`gate.py:246-277`) have **no auth and no rate limiting**.
- `apply_evolution` (`utils/personality.py:131`) writes `new_soul` to disk + DB **unconditionally**. The 13-pattern OWASP injection scan only runs in `propose_evolution` and returns an advisory `safe_to_apply` flag — **nothing server-side enforces it**. A direct `POST /soul/apply` overwrites the system-prompt identity layer and bypasses the scan, contradicting the project's "topology = enforcement, not prompts" principle for this path.
- `SoulEvolutionRequest` (`schemas/api.py:42-44`) has **no length limits** on `new_soul`/`reason` → unbounded disk/DB write, audit-log bloat, local DoS.
- *Mitigations present:* localhost bind, `.md.bak` backup on apply, SHA-256 version history.

**Fix:** enforce the injection scan inside `apply_evolution` (reject flagged content unless an explicit `force=True`); add `Field(max_length=...)` to the request model; apply `check_rate_limit` to the `/soul/*` mutating endpoints.

### F2 — `record_interaction()` call/signature mismatch — LOW (reliability)
`graph.py:296-302` calls it with `query=/answer=/model_used=/top_score=/hit_count=`, but the method is `record_interaction(self, query_hash, outcome)` (`utils/personality.py:150`). Every call raises `TypeError`, silently swallowed by `except Exception: pass` — the feature is dead and the errors are invisible.

**Fix:** align the call to `record_interaction(query_hash=hash_query(query), outcome=...)` (keeps raw query out of the DB), or update the signature.

### F3 — Local pickle deserialization of BM25 index — LOW (defense-in-depth)
`hybrid_search.py:72` `pickle.load(index/bm25.pkl)`. File is locally built and gitignored; only exploitable by someone who already has local write access to `index/`.

**Fix (optional):** store a companion SHA-256 of `bm25.pkl` and verify on load, or document the trust assumption.

### F4 — MCP generic exception echoes `str(e)` — LOW
`mcp_hybrid_server.py:67` returns raw exception text over stdio. Local-only, minor internal-detail disclosure.

### F5 — `SECURITY.md` PGP placeholder — INFO/cosmetic
`.github/SECURITY.md:12` still contains the literal `[PGP KEY FINGERPRINT or URL]`. Fill it in or remove the line.

### F6 — CORS `null` entry is a no-op, not a wildcard — INFO (clarification)
`config.yaml:129` `- null`. In Starlette, origins match by **exact string**; Python `None` never matches the literal `"null"` Origin header, so this entry allows **nothing** — it does *not* mean allow-all. The real boundary is the localhost bind. Optionally delete the line and its misleading comment.

### F7 — Bounded ReDoS patterns — INFO
`\s+`-based patterns in `utils/sanitizer.py` / `utils/personality.py` are practically safe given the 4000-char input cap and advisory use.

---

## Non-security observations

- **Deleting `ci.yml`** removed the automated test matrix on PRs — a regression-detection loss, not a security issue. It also retired the broken `python -c "import main"` step (there is no `main.py`). If you want CI back, add a minimal hardened workflow with `permissions: contents: read`.
- The dependabot bump pins a **release candidate** (`1.0.10rc1`) — expected for the CVE remediation, just noting the pre-release pin.

---

## Priority order

1. **F1** — enforce injection scan on `apply` + cap input sizes + rate-limit `/soul/*` *(the one finding that matters if exposure ever changes)*.
2. **F2** — fix the dead `record_interaction` call.
3. **F5 / F6** — cosmetic cleanups (PGP placeholder, CORS `null`).
4. **F3 / F4** — optional defense-in-depth.

No committed secrets, no exploitable injection/SSRF/XSS, no misconfigured remaining workflow. Clean bill of health for the intended use; the above hardens it against a future where it stops being localhost-only.





---

# PsyClaw Suggestions & Fixes for Refactor (v1.3.0)

## Summary
This document tracks the architectural changes, bug fixes, and open issues identified during the v1.3.0 refactor.

## Completed in v1.3.0
- [x] Rate limiting (60 req/min per IP, sliding window)
- [x] Soul SHA-256 drift detection on startup
- [x] Atomic soul writes (backup → DB → disk → memory)
- [x] Expanded to 13 OWASP injection patterns
- [x] interaction_ttl_days extended to 365
- [x] Telemetry kill block moved before any SDK import
- [x] `route_by_score` threshold corrected to 0.028 (RRF scale, not cosine)
- [x] Soul preamble injection hardened (labeled as untrusted context)

## Open Issues / v1.4.0 Targets
- [ ] Dropbox corpus sync (`dropbox_sync.py` placeholder)
- [ ] `plan_node` for multi-hop query decomposition
- [ ] `insightextractor.py` for automated corpus enrichment from query patterns
- [ ] Conversation compaction (rolling summary node)
- [ ] BM25 index SHA-256 integrity verification on load
- [ ] `static/terminal.html` API alignment (currently has endpoint mismatches)
- [ ] Config schema validation on startup (pydantic model for config.yaml)
- [ ] Weighted RRF option (currently equal 1.0/1.0 by design)

## Known Issues
- `static/terminal.html` has API response field mismatches vs current QueryResponse schema
- `vector_weight`/`bm25_weight` in config.yaml are documentation-only; actual weighting is equal
- `min_score` threshold comments reference cosine similarity but value is RRF scale
- LANGGRINCH ;)
