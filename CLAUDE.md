# CyClaw — Claude Code Memory

## Project Overview
CyClaw is a local-first RAG (Retrieval-Augmented Generation) gateway running on FastAPI + LangGraph + ChromaDB + BM25. It is designed as a loopback-only homelab tool with a strong security posture.

## Development Branch
Active development branch: `claude/jolly-cerf-v0vbjz`

## Last Verification Run
**Date:** 2026-06-20  
**Runtime:** Python 3.12  
**Base commit:** a80f9e0 (main at time of run)  
**Result:** 98/98 tests passed, all core paths functional.

## Open Findings (Unresolved as of 2026-06-20)

### Critical
- **F1** `utils/personality.py:168` — `apply_evolution()` has no injection scan. Live probe confirmed: `POST /soul/apply` with injection payload returns `200 applied`. Fix: mirror the `OWASP_INJECTION_PATTERNS` check from `propose_evolution()`.

### Medium
- **F2** `retrieval/hybrid_search.py:146` — Raw BM25/cosine scores bypass RRF-calibrated `min_score=0.028` gate on degraded fallback paths. Suppresses Grok confirmation prompt silently.
- **F3** `tests/ci_rag_smoke.py:62` — WARN branch returns 0; retrieval regressions ship undetected. Fix: `return 1`.
- **F4** `graph.py:212` — `cfg["policy"]["fallback"]` raises `KeyError` on partial config. Use `.get()`.
- **F5** `config.yaml:174` — String `"null"` in `allowed_origins` grants CORS to sandboxed iframes and `file://` pages. Remove it.
- **F6** `gate.py:80` — API key compared with `!=` (not timing-safe). Fix: `hmac.compare_digest()`.
- **F7** `mcp_hybrid_server.py:61` — Raw query text in MCP response metadata. Fix: use `hash_query()`.
- **F8** `gate.py` — FastAPI `/docs` and `/openapi.json` exposed. Fix: `docs_url=None, redoc_url=None, openapi_url=None`.
- **F9** `constraints.txt` — `setuptools==70.2.0` below CVE-2024-6345 fix (needs `>=70.3.0`).
- **F10** `.github/workflows/claude.yml:23,29` — Unpinned `actions/checkout@v4` and `anthropics/claude-code-action@beta` with broad write + `id-token: write` permissions.

### Low
- **F11** `gate.py:151` + 4 others — CWD-relative `config.yaml` opens. Fix: `Path(__file__).parent.parent / "config.yaml"`.
- **F12** `retrieval/indexer.py:89` — `build_index()` unconditionally destroys and rebuilds. Add `force=False` guard.
- **F13** `config.yaml:135` — `'urgent|action\s+required'` over-broad; blocks legitimate queries. Add `\b` anchors.
- **F14** `config.yaml:113` — `'act\s+as\s+if...'` is dead code; `'act\s+as'` fires first. Restructure pattern order.
- **F15** `gate.py` — No HTTP security headers (CSP, X-Frame-Options, X-Content-Type-Options). Add middleware.
- **F16** `static/terminal.html:844` — Meta tag values (`m.k`, `m.v`) not HTML-escaped before innerHTML insertion.
- **F17** `utils/personality.py` — Soul content stored verbatim in SQLite; no `chmod 700` enforced on `data/personality/`.
- **F18** `.github/workflows/codeql.yml`, `devskim.yml` — Floating action tags (`@v4`, `@v6`, `@v7`). Pin to SHAs.
- **F19** `.github/workflows/claude.yml` — `id-token: write` may be unnecessary for `claude-code-action`.

### Informational
- **F20** LM Studio unavailable → confusing `[LLM Error: ...]` shown inline in browser UI.
- **F21** `httpx` deprecation warning from FastAPI TestClient (future breaking change).
- **F22** `package.json` references non-existent `index.js`; unused `express` production dependency.

## Verified Positive Controls (Confirmed Working)
- DOM XSS: `escHtml()` on all LLM answer text
- Audit logs: query SHA-256 hashed, never raw
- Secret redaction in HTTP error responses (`_sanitize_error()`)
- No hardcoded credentials
- BM25 pickle → JSON migration complete (prior RCE resolved)
- Soul writes atomic (`os.replace()`)
- SQLite queries parameterized
- `CORS allow_credentials=False`
- MCP server `sampling: None` (cannot invoke LLM)
- Telemetry kill-switch before chromadb/langchain imports
- Rate limiter: 60 req/min enforced exactly
- Prompt injection gate: `400 PROMPT_INJECTION_BLOCKED` on known payloads
- NLTK `punkt` bypassed (avoids path-traversal CVE)
- CI `ci.yml`: actions SHA-pinned, `permissions: contents: read`

## Key Architecture Notes
- Loopback-only binding (`127.0.0.1`) is the primary threat model boundary
- `CYCLAW_API_KEY` unset = no auth on write endpoints (undocumented, by design)
- Two diverged injection pattern lists: `config.yaml` (30 patterns) vs `utils/personality.py` (13 patterns)
- LangGraph state machine routes: high-score → local LLM; low-score + online → Grok fallback; low-score + offline → best-effort
