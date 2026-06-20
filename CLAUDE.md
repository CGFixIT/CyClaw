# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

CyClaw is a Python FastAPI RAG server (`gate.py`) with a LangGraph security topology,
ChromaDB + BM25 retrieval, and a local LLM via LM Studio. It binds to `127.0.0.1:8787`.

Quick start: see `.claude/skills/run-cyclaw/SKILL.md`.

---

## Architecture

### Request Flow

```
HTTP POST /query  (or MCP tool call)
        │
        ▼
   gate.py  — rate limit → injection filter → soul init → graph invoke
        │
        ▼
   graph.py  (LangGraph 7-node state machine)
   retrieve → route_score
              ├─ score OK  → local_llm  (LM Studio :1234)
              └─ score low → user_gate
                             ├─ confirmed+hybrid → grok_fallback  (xAI)
                             └─ declined/offline → offline_best_effort
              ↓ (all six paths converge here)
              audit_logger → END
        │
        ▼
   HybridRetriever  — ChromaDB (semantic) + BM25Okapi (keyword) → RRF fusion
```

`retrieve` is the unconditional first node — no LLM call precedes retrieval.
Routing is enforced by graph edges, not LLM decisions.

### Key Modules

| Path | Role |
|---|---|
| `gate.py` | FastAPI entry, soul endpoints, API key auth, rate limit, sanitizer |
| `graph.py` | 7-node LangGraph topology; all security policy lives here |
| `retrieval/hybrid_search.py` | RRF fusion (k=60) over ChromaDB + BM25 |
| `retrieval/indexer.py` | Corpus ingestion, chunk sanitization |
| `llm/client.py` | `LocalLLMClient` (LM Studio) + `GrokClient` (xAI fallback) |
| `utils/sanitizer.py` | 31-pattern prompt-injection filter; patterns live in `config.yaml` |
| `utils/personality.py` | Soul versioning, SHA-256 drift detection, injection scan on write |
| `utils/logger.py` | Audit JSONL; SHA-256 query hashing, PII redaction |
| `utils/ratelimit.py` | Thread-safe per-IP rate limiting (60 req/min) |
| `schemas/api.py` | Pydantic models: `QueryRequest`, `QueryResponse`, `HealthResponse`, etc. |
| `metrics.py` | `audit.jsonl` analyzer |
| `mcp_hybrid_server.py` | MCP server (retrieval only, no LLM, no `sampling`) |
| `sync/` | Out-of-band Dropbox corpus sync via `rclone`; never imported by gate/graph |

### Configuration

`config.yaml` is the single source of truth for all tunables. Key sections:

- `app.mode` — `"offline"` (default) or `"hybrid"` (enables Grok fallback)
- `models.local_llm` — LM Studio endpoint, model, timeout, max_tokens
- `models.grok` — xAI fallback (disabled by default)
- `retrieval.top_k`, `retrieval.min_score` — RRF result count and score floor
- `policy.prompt_filter.banned_patterns` — 31 injection patterns (authoritative list)
- `policy.privacy` — PII redaction rules (emails, IPs, secrets)
- `api.host` / `api.port` — `127.0.0.1:8787`
- `sync` — optional Dropbox rclone integration (disabled by default)

### Security Invariants

Five invariants enforced by graph topology (not prompts):

1. **RAG-First** — `retrieve` is the unconditional entry; no LLM precedes it.
2. **Topology = Policy** — routing is graph edges only, never LLM-decided.
3. **Triple-Gated External** — Grok requires `mode=hybrid` AND `grok.enabled=true` AND `user_confirmed_online=true` simultaneously.
4. **Audit Convergence** — all 6 execution paths converge at `audit_logger`; no shortcut exists.
5. **Soul Governance** — soul evolution requires an explicit human reason string; no autonomous modification from any path.

Additional layers: loopback-only binding, atomic soul writes (`os.replace` + injection scan), SHA-256 query hashing in audit log (raw text never persisted).

### Dependency Notes

- **chromadb** has a known CVE (pre-auth RCE); accepted because only `PersistentClient` (embedded) is used — `pip-audit` ignores it per threat model.
- **torch** must be installed separately (`pip install torch==2.6.0+cpu`) **before** `requirements.txt` to avoid the CVE-2025-32434 `weights_only` bypass in earlier versions.
- Install requirements with: `pip install -r requirements.txt --ignore-installed PyYAML` (PyYAML version conflict with system packages).

---

## Git Identity

Set this at the start of every session before making any commits:

```bash
git config user.email noreply@anthropic.com
git config user.name Claude
```

The stop hook rejects commits whose committer email is not `noreply@anthropic.com`.

---

## Branch & PR Workflow

- Develop on the designated feature branch (`claude/<name>`).
- **Do not push directly to `main` via the GitHub MCP** when a feature branch and open PR
  exist — doing both creates add/add conflicts on rebase. Commit only to the feature
  branch and let the PR merge carry changes into main.
- After a force-push (required after rebasing), confirm with the user first — the
  auto-permission classifier blocks `--force-with-lease` without explicit authorization.

---

## Tests

```bash
GROK_API_KEY=dummy pytest tests/ -q --tb=short
# Run a single test file:
GROK_API_KEY=dummy pytest tests/test_graph.py -q --tb=short
```

CI target is Python 3.12. `GROK_API_KEY` must be set (any non-empty value works offline).
Coverage target is 80% (`pyproject.toml`).

Test categories: `test_gate`, `test_graph`, `test_hybrid_search`, `test_personality`,
`test_sanitizer`, `test_audit`, `test_rate_limit`, `test_mcp_server`, `test_security`,
`test_telemetry_kill`, `test_sync_*` (5 files).

---

## Skills

Skills live at `.claude/skills/<name>/SKILL.md`. When a user invokes a skill not
present in the local sandbox, **check GitHub main before declaring it absent**:

```bash
# or use mcp__github__get_file_contents with path .claude/skills/<name>/SKILL.md
```

Available skills (all on `main`):

| Skill | Type | Purpose |
|---|---|---|
| `/run-cyclaw` | one-shot | Smoke-test the FastAPI server |
| `/architecture-refactor` | loop | Iterative architecture cleanup |
| `/speed-refactor` | loop | Optimize all endpoints to <50 ms |
| `/tests-refactor` | loop | Coverage to 100%, pass rate ≥85% |
| `/logging-refactor` | loop | Log coverage on every important path |
| `/wrap-up` | one-shot | End-of-session checklist |

---

## Environment Quirks

- `status: degraded` in `/health` is normal without LM Studio running.
- `TELEMETRY KILL` messages on startup are intentional (LangChain/Chroma/OTel env vars blocked).
- Soul file must exist at `data/personality/soul.md` before server start.
- Entry points (from `pyproject.toml`): `cyclaw-server`, `cyclaw-index`, `cyclaw-mcp`, `cyclaw-metrics`.
