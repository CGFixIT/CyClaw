---
name: run-cyclaw
description: Run, start, build, smoke-test, or interact with the CyClaw FastAPI RAG server. Use when asked to run cyclaw, start the server, test a change, verify an endpoint, or confirm the app is working.
---

# Run CyClaw

CyClaw is a Python FastAPI server (`gate.py`) that exposes a RAG pipeline over
a local ChromaDB + BM25 index. It binds to `127.0.0.1:8787`. The driver is a
curl-based smoke script at `.claude/skills/run-cyclaw/smoke.sh`.

LM Studio is an **external dependency** (the local LLM). CI and the smoke
script run without it: the `/query` path degrades gracefully (offline-best-effort
returns an `[LLM Error: ...]` answer), and all structural flows are testable.

---

## Prerequisites

```bash
# Python 3.12 required
# Install torch CPU first (avoids PyPI torch pulling CUDA)
pip install torch==2.6.0+cpu --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt --ignore-installed PyYAML
```

PyYAML conflict is harmless — the system version works fine; skip the
reinstall with `--ignore-installed PyYAML`.

---

## Build (retrieval index)

Must be run once before the server starts; idempotent. The smoke script backs up
your real `soul.md` before building, uses a minimal temp one, and restores it
when done:

```bash
mkdir -p data/personality index logs
GROK_API_KEY=dummy python3 -m retrieval.indexer
```

Expected output: `[Indexer] Done. ChromaDB: index/chroma_db, BM25: index/bm25.json`

Your `data/personality/soul.md` is never modified by the smoke test.

---

## Run (agent path — smoke driver)

The smoke script launches the server, runs 6 checks covering all major
API paths, and exits 0/1:

```bash
bash .claude/skills/run-cyclaw/smoke.sh
```

Checks performed (all verified in this session):
1. `GET /health` — index_ready=True, graph_ready=True
2. `POST /query` — vault-miss path returns `needs_confirm=True`
3. `POST /query` with `user_confirmed_online=false` — exercises
   `offline_best_effort` graph node (expects LLM error without LM Studio)
4. Prompt injection blocked → HTTP 400
5. `GET /soul` — personality endpoint live
6. `GET /static/terminal.html` — static UI served

---

## Run (human path)

```bash
GROK_API_KEY=dummy uvicorn gate:app --host 127.0.0.1 --port 8787
```

Then open `http://127.0.0.1:8787` in a browser (the Soul Console terminal UI).
Useless headless; use the smoke driver instead.

---

## Interact via curl

```bash
BASE="http://127.0.0.1:8787"

# Health
curl -s $BASE/health | python3 -m json.tool

# Query (offline, no LM Studio needed for graph flow)
curl -s -X POST $BASE/query \
  -H "Content-Type: application/json" \
  -d '{"query":"What is RRF fusion?"}' | python3 -m json.tool

# Confirm offline path (decline Grok)
curl -s -X POST $BASE/query \
  -H "Content-Type: application/json" \
  -d '{"query":"What is CyClaw?","user_confirmed_online":false}' \
  | python3 -m json.tool

# Soul
curl -s $BASE/soul | python3 -m json.tool
```

---

## Tests

```bash
GROK_API_KEY=dummy pytest tests/test_sanitizer.py tests/test_security.py \
  tests/test_rate_limit.py tests/test_audit.py tests/test_personality.py \
  -q --tb=short
```

---

## Gotchas

- **`status: degraded`** in `/health` is normal without LM Studio running.
  `index_ready` and `graph_ready` are the meaningful fields for smoke testing.
- **`needs_confirm: true`** on `/query` is correct behavior when the top
  retrieval score is below `min_score` (0.028). The corpus has only one
  document in the dev index, so scores hover near zero. Re-submit with
  `user_confirmed_online: false` to exercise the full graph path.
- **PyYAML install conflict** — `pip install -r requirements.txt` errors on
  the system-installed PyYAML. Use `--ignore-installed PyYAML`; the system
  version is compatible.
- **TELEMETRY KILL messages** printed to stdout on server start are
  intentional (gate.py kills LangChain/Chroma phone-home hooks at startup).
- **`GROK_API_KEY`** must be set (any non-empty value works) — gate.py checks
  `security.require_env` at startup and warns if missing. `dummy` is fine for
  offline mode.
- **`soul.md` preservation** — The smoke script backs up your real
  `data/personality/soul.md`, uses a minimal temp one during the test, and
  restores the original afterward. Your personality file is guaranteed to be
  unmodified.
