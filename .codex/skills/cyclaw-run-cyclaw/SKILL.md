---
name: cyclaw-run-cyclaw
description: >-
  Codex-native CyClaw runtime workflow. Use when working in CGFixIT/CyClaw and the user asks to run, start, build, smoke-test, interact with, or verify the CyClaw FastAPI RAG server, retrieval index, local endpoints, or runtime test suite.
---

# CyClaw Run CyClaw

Use this skill to prepare, run, and verify the CyClaw FastAPI RAG server. CyClaw
binds to `127.0.0.1:8787`, uses local retrieval over ChromaDB + BM25, and
degrades gracefully when LM Studio is unavailable.

Run setup, server, or test commands only when the user asks for execution.
Respect the active Codex sandbox and approval rules, especially for installs,
network access, server processes, and filesystem writes.

## Setup

Python 3.12 is expected. Prefer the repo's current setup guidance in
`AGENTS.md`, `.github/copilot-instructions.md`, and `docs/SETUP.md`.

CPU torch must be installed before the rest of the Python dependencies:

```bash
python -m pip install --upgrade "pip>=26.1.2"
pip install torch==2.12.1+cpu --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt --ignore-installed PyYAML
```

Use `pyproject.toml` plus `constraints.txt` or `uv` when the environment already
supports that path. Do not install dependencies unless runtime verification
requires it and approvals allow it.

## Runtime Prep

Create required runtime directories and a dummy offline key when needed:

```bash
mkdir -p data/personality index logs
test -f data/personality/soul.md || printf '# Soul\n' > data/personality/soul.md
export GROK_API_KEY=dummy
```

Do not overwrite an existing `data/personality/soul.md`.

## Build Retrieval Index

Build or refresh the index when `index/` is missing or `data/corpus/` changed:

```bash
GROK_API_KEY=dummy python -m retrieval.indexer
```

Expected output should identify `index/chroma_db` and `index/bm25.json`.

## Run Server

Start the gateway on loopback:

```bash
GROK_API_KEY=dummy uvicorn gate:app --host 127.0.0.1 --port 8787
```

Installed entry point equivalent:

```bash
cyclaw-server
```

Do not bind to `0.0.0.0` unless the user explicitly requests a deployment
change and accepts the security implications.

## Endpoint Probes

With the server running:

```bash
BASE="http://127.0.0.1:8787"
curl -s "$BASE/health" | python -m json.tool
curl -s -X POST "$BASE/query" \
  -H "Content-Type: application/json" \
  -d '{"query":"What is CyClaw?","user_confirmed_online":false}' | python -m json.tool
curl -s "$BASE/static/terminal.html"
```

For `/soul`, set a dummy local API key only for local smoke testing:

```bash
export CYCLAW_API_KEY="smoke-test-key-ci"
curl -s "$BASE/soul" -H "Authorization: Bearer $CYCLAW_API_KEY" | python -m json.tool
```

## Tests

Prefer focused tests for changed areas. Common runtime checks:

```bash
python -m tests.ci_rag_smoke
GROK_API_KEY=dummy pytest tests/ -q --tb=short --continue-on-collection-errors
```

Agentic checks:

```bash
GROK_API_KEY=dummy pytest tests/test_agentic_*.py -q
python -m agentic.cli test
```

Postgres and pgvector checks are opt-in and require `CYCLAW_DB_URL` plus the
required database extensions:

```bash
CYCLAW_DB_URL=postgresql://... CYCLAW_DB_SSLMODE=disable \
  pytest tests/test_personality_postgres.py tests/test_ratelimit_postgres.py \
         tests/test_pgvector_store.py -q
```

## Expected Runtime Signals

- `/health` can be `degraded` without LM Studio; `index_ready` and
  `graph_ready` are the important structural fields.
- Low retrieval scores may require offline confirmation and produce
  `needs_confirm: true`.
- Prompt injection should fail closed with an error response.
- Telemetry-kill startup messages are intentional.
- `GROK_API_KEY=dummy` is enough for offline/local verification.
- Postgres, rclone, LM Studio, and live GitHub auth should be optional unless
  the user explicitly asks to exercise those integrations.

## Final Report

Include:

- prep commands run
- server command and whether it stayed running or was stopped
- endpoint/test results
- external dependencies that were unavailable
- generated runtime files that were intentionally left uncommitted

## Guardrails

- Preserve loopback-only binding.
- Do not mutate an existing soul file.
- Do not commit `logs/`, `index/`, caches, coverage, local env files, or secrets.
- Keep optional `sync/`, `agentic/`, and `guardrails/` layers optional for core
  gateway operation.
