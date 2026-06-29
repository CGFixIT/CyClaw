---
name: cyclaw-command-run
description: >-
  Codex-native CyClaw smoke-run workflow. Use when working in CGFixIT/CyClaw and the user asks to run CyClaw checks, smoke-test the local server, verify endpoints, confirm the app works, or exercise health/query/soul/static routes.
---

# CyClaw Command Run

Use this skill to run or guide CyClaw smoke verification against the local
FastAPI server. Prefer repo-native tests and explicit endpoint probes over
legacy agent scripts.

Run commands only when the user asks to execute the checks. Starting a server or
probing local endpoints may require sandbox approval depending on the session.

## Prerequisites

Confirm these exist before live endpoint checks:

- `index/chroma_db/`
- `index/bm25.json`
- `data/personality/soul.md`
- Python dependencies for FastAPI, retrieval, and tests

If index files are missing, build them first when approved:

```bash
mkdir -p data/personality index logs
GROK_API_KEY=dummy python -m retrieval.indexer
```

## Preferred Verification

Use the fastest meaningful check first:

```bash
python -m tests.ci_rag_smoke
GROK_API_KEY=dummy pytest tests/ -q --tb=short
```

For endpoint-level smoke, run the server:

```bash
GROK_API_KEY=dummy uvicorn gate:app --host 127.0.0.1 --port 8787
```

Then probe:

```bash
curl -s http://127.0.0.1:8787/health
curl -s -X POST http://127.0.0.1:8787/query \
  -H "Content-Type: application/json" \
  -d '{"query":"What is CyClaw?","user_confirmed_online":false}'
curl -s http://127.0.0.1:8787/static/terminal.html
```

For `/soul`, use a dummy local key only when the server is configured for it:

```bash
curl -s http://127.0.0.1:8787/soul -H "Authorization: Bearer $CYCLAW_API_KEY"
```

## Expected Signals

- `/health` may report `status: degraded` without LM Studio; focus on
  `index_ready` and `graph_ready`.
- Offline query paths should remain local and avoid Grok unless hybrid mode and
  user confirmation gates are explicitly enabled.
- Prompt injection tests should fail closed.
- Static terminal UI should return HTTP 200 when static files are mounted.

## Report

Include:

- checks run
- pass/fail status
- endpoint details for failures
- whether LM Studio, Grok, Postgres, rclone, or `gh` were unavailable
- residual risk and next verification step

## Guardrails

- Keep the server bound to `127.0.0.1`.
- Use `GROK_API_KEY=dummy` for offline verification.
- Do not require LM Studio, Grok, rclone, Postgres, or real GitHub tokens for
  ordinary smoke checks.
- Do not commit generated logs, indexes, caches, or local runtime files.
