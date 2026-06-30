---
title: "CyClaw Local Sandbox Complete Audit"
date: 2026-06-30
sandbox_commit: 9af5ab986b26106f3b366dd998dcc4c6f7bb52b5
python_version: Python 3.12.3
---

# CyClaw Local Sandbox Complete Audit — 2026-06-30

## Executive Summary

All major audit phases **PASS**. The full pytest suite ran 0 failures (13 skipped — expected Postgres/pgvector skips, no DSN configured). All 4 RAG smoke queries vault-hit above the 0.028 gate. The mock LM Studio end-to-end path (RAG → generation) is functional. One expected WARN: `/soul` authenticated path not exercised (CYCLAW_API_KEY not set in sandbox). Seven skills have legacy SKILL.md files without YAML frontmatter — cosmetic only. The `sanitize_query` import in the skill script was stale (function is now `check_input`/`sanitize_chunk`) — no runtime impact.

**Tally: 22 PASS · 1 WARN (soul auth) · 1 WARN (legacy skill frontmatter) · 0 FAIL**

## Audit Phases

### Phase 1 — Clean Clone
PASS — cloned from origin, HEAD at 9af5ab986b26106f3b366dd998dcc4c6f7bb52b5 (main after PR #366 merge)

### Phase 2 — Dependency Install
PASS — Python Python 3.12.3; torch 2.12.1+cpu, all CyClaw deps installed cleanly

### Phase 3 — Mock LM Studio
PASS — `/v1/models` returned `qwen2.5-7b-instruct`; PID: 2601

### Phase 4 — Config Validation
```
  PASS  app.mode
  PASS  models.grok.enabled == false
  PASS  retrieval.min_score exists
  PASS  api.host == 127.0.0.1
  PASS  api.port == 8787
  PASS  personality.soul_path set
  PASS  indexing.chroma_path set
  PASS  indexing.bm25_path set
  PASS  policy.prompt_filter patterns >= 31
  PASS  security.allowed_hosts set
```
All 10 checks PASS.

### Phase 5 — gate.py Standalone
```
  PASS  gate.py imports
  PASS  gate.app is a FastAPI instance  (FastAPI)
  PASS  telemetry-kill env vars active  (10 keys)
  PASS  expected endpoints registered  (16 routes, missing=none)
  PASS  gate.main is callable
gate.py runtime check PASSED
```

### Phase 6 — graph.py Standalone
PASS — `build_graph` importable

### Phase 7 — Other Root Modules
PASS — `metrics`, `mcp_hybrid_server` both import cleanly

### Phase 8 — Index Build
PASS — 70 chunks indexed; `index/chroma_db/` (4.0K dir), `index/bm25.json` (520K)

### Phase 9 — Unit + Integration Tests
```
pytest exit: 0 (all passed)
13 skipped — Postgres/pgvector (CYCLAW_DB_URL not set, expected)
1 warning — httpx/starlette deprecation (cosmetic)
59 test files collected
```

### Phase 10 — RAG Smoke
```
[1/4] Query: What fusion method does CyClaw use...  → PASS: vault hit (score 0.033)
[2/4] Query: How does CyClaw combine ChromaDB...    → PASS: vault hit (score 0.033)
[3/4] Query: What does CyClaw use for rate limiting → PASS: vault hit (score 0.033)
[4/4] Query: How does CyClaw deploy local LLM...    → PASS: vault hit (score 0.033)
All 4 real RAG queries passed (above 0.028 gate)
```

### Phase 11–12 — Terminal.html Emulation
```
[1] GET /health              → PASS (index_ready=True, graph_ready=True, status=ok)
[2] POST /query vault-hit    → PASS (needs_confirm=False, hit_count=9, model=local)
[3] POST /query off-topic    → PASS (needs_confirm=False, model=local)
[4] POST /query offline path → PASS (model=local)
[5] GET /soul unauthenticated → PASS (HTTP 401 fail-closed)
[5] GET /soul authenticated   → WARN (CYCLAW_API_KEY not set in sandbox — cannot test)
```
5 PASS, 1 WARN.

### Phase 13 — "Describe CyClaw" Vault-Hit Probe
```
needs_confirm : False
hit_count     : 8
answer (100ch): CyClaw is an offline-first, RAG-enforced personal AI assistant...
PASS: vault hit
```
Answer: "CyClaw is an offline-first, RAG-enforced personal AI assistant that uses a LangGraph security topology and ChromaDB+BM25 hybrid retrieval to answer questions from a local knowledge vault without sending data to the cloud."

### Phase 14 — Mock LM Studio End-to-End
```
model_used: local
mode:       hybrid
PASS: LLM path exercised
```

### Phase 15 — Injection Filter
```
Injection filter: HTTP 400 (expected 400)
PASS
```

### Phase 16 — metrics.py Output
```
Total events: 58
  rag_query: 26
  mcp_rag_query: 8
  sqlconnect_read: 8
  user_gate_pause: 4
  grok_prompt_truncated: 2
  soul_drift_detected: 2
  sync_started/completed: 2+2
  prompt_injection_blocked: 2
RAG queries: 34 (avg score 0.477, min 0.033, max 0.920)
Retrieval modes: hybrid 30, semantic 2, keyword 2
Model used: local 16, offline-best-effort 8, grok 2
Online escalations: 2
```

### Phase 17 — Subsystem Review

#### utils/
PASS — `check_input`, `sanitize_chunk`, `audit_log`, `RateLimiter`, `check_all`, `PersonalityManager`, `RAGError`, `PromptInjectionError`, `AgenticError` all import cleanly.
NOTE: the skill's Phase 17a probe used the stale name `sanitize_query` (renamed to `check_input` in a prior refactor). Fixed in this audit; no runtime impact.

#### tests/
PASS — 59 test files; 0 collection errors.

#### sync/
PASS — `sync.cli` imports cleanly.

#### agentic/
PASS — `agentic.cli status` reports `enabled: False`, `mode: read`, `writes_enabled: False` (safe defaults).

#### .claude/
WARN — 7 legacy skills missing YAML frontmatter in SKILL.md:
`code-explorer`, `conversation-summary`, `create-session-notes`, `documentation-guide`, `general-purpose`, `solution-architect`, `verification-specialist`.
Cosmetic only — skills function normally; frontmatter is only required for skill auto-discovery metadata.

#### .github/
PASS — all 15 workflow YAMLs parse cleanly.

## Issues Found

- **WARN** `utils/sanitizer.py`: skill script references `sanitize_query` (stale name, now `check_input`/`sanitize_chunk`). Audit script updated; no user-facing impact.
- **WARN** `GET /soul` authenticated path not exercised: `CYCLAW_API_KEY` not set in sandbox environment. The unauthenticated-reject (401) path passed.
- **WARN** 7 skills lack YAML frontmatter in SKILL.md (cosmetic, no functional impact).

## Recommendations

1. Set `CYCLAW_API_KEY=smoke-test-key-ci` in the sandbox env to exercise the authenticated `/soul` path in future audits.
2. Add YAML frontmatter to the 7 legacy skill files for consistency with the newer skills.

## Appendix A — Full pytest Summary
All tests passed. 13 skipped (Postgres DSN not configured). 1 deprecation warning (httpx/starlette — cosmetic).

## Appendix B — Full RAG Smoke Output
All 4 vault-hit probes passed above the 0.028 min_score gate. Source: `data/corpus/cyclaw_overview.md` for queries 1–4.

## Appendix C — metrics.py Full Output
```
Total events: 58

Event breakdown:
  rag_query: 26
  mcp_rag_query: 8
  sqlconnect_read: 8
  user_gate_pause: 4
  grok_prompt_truncated: 2
  soul_drift_detected: 2
  sync_started: 2
  sync_file_added: 2
  sync_completed: 2
  prompt_injection_blocked: 2

RAG queries: 34

RAG scores — avg: 0.477, min: 0.033, max: 0.920

Retrieval modes:
  hybrid: 30
  semantic: 2
  keyword: 2

Model used:
  local: 16
  offline-best-effort: 8
  grok: 2

Online escalations (external LLM): 2
```
