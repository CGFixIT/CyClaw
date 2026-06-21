# CyClaw

> **Offline-first, RAG-enforced, soul-governed personal AI assistant (no internet required!)**
> Version 1.5.0 (Out-of-band agentic layer + LangGraph memory nodes + Docker)

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-green.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.1-orange.svg)](https://github.com/langchain-ai/langgraph)
[![CodeQL Advanced](https://github.com/CGFixIT/CyClaw/actions/workflows/codeql.yml/badge.svg)](https://github.com/CGFixIT/CyClaw/actions/workflows/codeql.yml)
[![CyClaw CI (Simplified + Coverage)](https://github.com/CGFixIT/CyClaw/actions/workflows/ci.yml/badge.svg)](https://github.com/CGFixIT/CyClaw/actions/workflows/ci.yml)[![Fortify AST Scan](https://github.com/CGFixIT/CyClaw/actions/workflows/fortify.yml/badge.svg?branch=main)](https://github.com/CGFixIT/CyClaw/actions/workflows/fortify.yml)<hr>
[![Screenshots: local AI](https://i.imgur.com/kGZBkIj.png)](https://github.com/CGFixIT/CyClaw/tree/main/docs/screenshots)   <-- Screenshots of Local AI web interface

---

## What It Does

CyClaw is a personal RAG (Retrieval-Augmented Generation) backend that:

1. **Answers questions exclusively from your local Markdown corpus** — no internet by default
2. **Enforces every safety invariant via LangGraph topology** — not prompts, not config flags, not discipline
3. **Maintains a persistent soul/personality layer** (`soul.md`) with SHA-256 drift detection, atomic evolution writes, and user-gated modification
4. **Falls back to Grok (xAI) only with explicit user confirmation** in hybrid mode — triple-gated at config, env, and per-query level
5. **Exposes both a FastAPI HTTP gateway and an MCP server** for Claude Desktop / Copilot Studio integration
6. **Ships an optional, disabled-by-default agentic layer** (`agentic/`) for read-only GitHub context and a governed skills registry — entirely out-of-band, never imported by the request path (v1.5.0)

Zero telemetry. Binds to `127.0.0.1:8787` only. All embeddings run locally via `sentence-transformers`. No cloud dependency for offline operation. Reproducible containerized deployment via Docker + Compose (v1.5.0).

---

## Version History

| Version | Status | Key Changes |
|---|---|---|
| v1.2.0 | Superseded | 8 OWASP patterns, 90-day TTL, sanitizer baseline |
| v1.3.0 | **Pre-Langgrinch** | Rate limiting (60/min), 13 OWASP patterns, soul SHA-256 drift detection, atomic writes, TTL→365 days |
| v1.4.0 | Superseded | Dropbox/cloud corpus sync (out-of-band rclone wrapper + full audit integration) + requirements.txt pinned for Python 3.12 + vuln patches |
| v1.5.0 | **Production (current)** | Out-of-band agentic layer (read-only GitHub via `gh` CLI + governed skills registry, disabled by default, write-scaffold stubbed & non-executing) · memory-orchestrator refactored into reusable LangGraph nodes (`memory_nodes.py`, full CLI/hook backward compat) · LangGraph SQLite checkpointer for resumable sessions · Docker + docker-compose (non-root, seccomp-ready, telemetry-killed) · strict Pydantic (`extra='forbid'`) on all API schemas · SQLite-persisted rate limiting · CI skill-verify matrix · dependency-comment consistency + Chroma CVE threat-model alignment |
| v1.6.0 | **Planning** | Fix Stemmer.py, sql write placeholder code sections, other cleanups, BM25 SHA Integrity Detection, Dropbox sync hardening & scheduler polish |

---

## Architecture

```
User Query (HTTP POST /query or MCMC tool call)
         │
         ▼
    ┌─────────────────────────────────────────────────────┐
    │  gate.py  (FastAPI, 127.0.0.1:8787)                 │
    │  • Rate limit (60 req/min per IP — RUNS FIRST)      │
    │  • Injection filter (sanitizer.py, config-driven)   │
    │  • Soul init (PersonalityManager closure)           │
    │  • Telemetry kill block (before any SDK import)     │
    └──────────────────┬──────────────────────────────────┘
                       │
                       ▼
    ┌─────────────────────────────────────────────────────┐
    │  graph.py  (LangGraph 7-node State Machine)         │
    │                                                     │
    │  [ENTRY]                                            │
    │     ↓                                               │
    │  1. retrieve  (Chroma + BM25 + RRF fusion)          │
    │     ↓                                               │
    │  2. route_score  (top_score >= 0.028 RRF?)          │
    │     ├─ YES ──→ 3. local_llm (LM Studio :1234)       │
    │     └─ NO  ──→ 4. user_gate (needs_confirm=true)    │
    │                    ├─ confirmed + hybrid ──→        │
    │                    │      5. grok_fallback          │
    │                    └─ declined / offline ──→        │
    │                           6. offline_best_effort    │
    │     ↓ (all paths converge)                          │
    │  7. audit_logger (SHA-256 + PII redact → jsonl)     │
    │     ↓                                               │
    │  [END]                                              │
    └─────────────────────────────────────────────────────┘
                       │
                       ▼
    ┌─────────────────────────────────────────────────────┐
    │  HybridRetriever  (retrieval/hybrid_search.py)      │
    │  • ChromaDB  (semantic, all-MiniLM-L6-v2, 384d)    │
    │  • BM25Okapi (keyword, Porter stemming)             │
    │  • RRF fusion (k=60, equal 1.0/1.0 weighting)      │
    │  • Per-chunk provenance metadata in every result    │
    └─────────────────────────────────────────────────────┘
```

**Five security invariants enforced by graph edges — not prompts:**

| # | Invariant | Enforcement |
|---|---|---|
| 1 | RAG-First | `retrieve` is the unconditional graph entry point — no LLM call can precede it |
| 2 | Topology = Policy | Routing is graph edges, not LLM decisions or if/else code |
| 3 | Triple-Gated External | Grok requires: `mode=hybrid` AND `grok.enabled=true` AND `user_confirmed_online=true` — simultaneously |
| 4 | Audit Convergence | All 6 execution paths converge at `audit_logger` — no shortcut path exists |
| 5 | Soul Governance | Soul evolution requires explicit human reason string; no autonomous modification from any path |

---

## Quick Start

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12 | Primary supported runtime (3.11 also works) |
| [LM Studio](https://lmstudio.ai/) | Any | Must be running on `localhost:1234` |
| GGUF model loaded in LM Studio | — | `mistral-7b-instruct` or `qwen2.5-7b` work well |

### Install

```bash
git clone https://github.com/CGFixIT/CyClaw
cd CyClaw
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 1) Install CPU-only torch first (pinned >=2.6.0 for CVE-2025-32434 safety)
pip install torch==2.6.0+cpu --index-url https://download.pytorch.org/whl/cpu

# 2) Install the rest, pinned to the verified transitive tree.
pip install -r requirements.txt -c constraints.txt
```

<hr>

[Detailed Setup Guide](https://github.com/CGFixIT/CyClaw/blob/main/setup-guide.md)

<hr>

### Configure

Key settings in `config.yaml`:

```yaml
app:
  mode: "offline"          # "offline" | "hybrid" (hybrid enables Grok fallback)

models:
  local_llm:
    base_url: "http://127.0.0.1:1234/v1"   # LM Studio default
    model: "your-model-name-here"           # must match LM Studio loaded model name exactly
    timeout_sec: 720                        # long-context inference budget
    max_tokens: 5000

personality:
  enabled: true
  soul_path: "data/personality/soul.md"    # your identity file — source of truth
  interaction_ttl_days: 365               # audit window

retrieval:
  min_score: 0.028          # RRF fused-rank threshold (NOT cosine sim — different scale)
  top_k_semantic: 5
  top_k_keyword: 5
  rrf_k: 60
  max_context_tokens: 5000
```

---

## Project Structure

```
CyClaw/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── SECURITY.md
│   ├── dependabot.yml
│   └── workflows/                 # CI workflows (codeql, ci, fortify, etc.)
├── .osv-scanner.toml
├── Dropbox_Sync_Guide.md
├── README.md
├── config.yaml                    # Single source of truth for all config
├── constraints.txt
├── cyclaw_telemetry_kill.env      # Kill-switch for LangChain/Chroma/OTel telemetry
├── gate.py                        # FastAPI gateway + soul endpoints
├── graph.py                       # LangGraph 7-node state machine
├── mcp_hybrid_server.py           # MCP server (retrieval-only, no LLM)
├── metrics.py                     # Audit JSONL analyzer
├── Dockerfile                     # Multi-stage, non-root, offline-first (v1.5+)
├── docker-compose.yml             # Non-root, seccomp-ready, telemetry-killed (v1.5+)
├── agentic/                       # Out-of-band agentic layer (disabled by default, v1.5+)
│   ├── __init__.py
│   ├── cli.py                     # `python -m agentic.cli {status,test,...}`
│   ├── config.py
│   ├── context.py                 # read-only GitHub context
│   ├── gh_client.py               # gh CLI wrapper (argv-list, no token forwarded)
│   ├── registry.py                # governed skills registry + governance_score
│   ├── writer.py                  # write scaffold (EXECUTION_ENABLED=False, stubbed)
│   └── selftest.py
├── deploy/
│   └── seccomp/                   # seccomp profile(s) for container hardening
├── pyproject.toml
├── requirements.txt               # Pinned Python deps
├── setup-guide.md
├── data/
│   ├── corpus/                    # .md / .txt knowledge base (gitignored at commit)
│   └── personality/
│       └── soul.md                # Identity source-of-truth
├── docs/
│   ├── screenshots/
│ 
│   ├── SETUP.md / setup-guide.md
│   └── (security reviews, architecture guides, etc.)
├── llm/
│   └── client.py                  # LocalLLMClient + GrokClient
├── retrieval/
│   ├── embeddings.py              # sentence-transformers wrapper
│   ├── hybrid_search.py           # ChromaDB + BM25 + RRF fusion
│   ├── indexer.py                 # Corpus ingestion + index build
│   └── stemmer.py                 # Porter stemmer (tech-vocabulary tuned)
├── schemas/
│   └── api.py                     # Pydantic request/response models
├── static/
│   ├── extractor.html             # Browser-Based simplified insight_extractor.py
│   └── terminal.html              # Browser UI / Soul Console
├── sync/                          # Out-of-band Dropbox corpus sync (rclone wrapper, v1.4+)
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── filters.py
│   ├── runner.py
│   ├── scheduler.py
│   └── selftest.py
├── tests/                         # Comprehensive pytest + PowerShell test suite
│   ├── conftest.py
│   ├── test_*.py (gate, graph, hybrid_search, personality, sync_*, rate_limit, sanitizer, etc.)
│   ├── apipsTest.ps1
│   └── cmd2index.bat
└── utils/
    ├── errors.py                  # Typed RAGError hierarchy
    ├── health.py                  # Startup dependency health checks
    ├── logger.py                  # Audit JSONL + SHA-256 query hashing
    ├── personality.py             # PersonalityManager (soul CRUD + governance)
    ├── ratelimit.py
    └── sanitizer.py               # Prompt injection filter + PII redaction
```

---

## Soul / Personality Layer

CyClaw maintains a persistent identity through `soul.md`. Key properties:

- **File-as-truth**: `data/personality/soul.md` is always the canonical version
- **Shadow SQLite DB**: `cyclaw_soul.db` stores version history and interaction logs
- **SHA-256 drift detection**: on startup, file hash vs. DB hash — mismatch triggers forensic log entry
- **Atomic writes**: backup → atomic disk write (`tmp` file + `os.replace`) → DB version insert → in-memory update; the `os.replace` is what makes a crash unable to leave a half-written `soul.md`
- **Advisory injection scan on propose**: `POST /soul/propose` runs an OWASP injection scan whose flags are **advisory** — surfaced for human review alongside the diff; `propose` never writes
- **Enforced injection scan on apply**: `POST /soul/apply` is human-gated (explicit reason string required) **and** re-runs the injection scan at the write boundary — a proposed soul containing injection patterns is rejected with `400 PROMPT_INJECTION_BLOCKED` before any file/DB write, closing the soul-poisoning vector. The trusted restore path (`restore_from_backup`, re-applying a previously vetted `.bak`) bypasses the scan via `scan=False`

---

## Security Model

| Layer | Mechanism |
|---|---|
| Network | Binds `127.0.0.1:8787` — no external exposure by design |
| Input | Config-driven injection filter (`policy.prompt_filter`, 31 patterns), 4000 char max |
| Rate limit | 60 req/min per IP — thread-safe in-memory sliding window (`utils/ratelimit.py`, lock-guarded) |
| Telemetry | Kill block runs before any SDK import in `gate.py` |
| Audit | All paths (HTTP and MCP) log SHA-256 query hash + PII-redacted metadata |
| Grok gating | Triple gate: `mode=hybrid` AND `grok.enabled=true` AND `user_confirmed_online=true` |
| Soul writes | Enforced injection scan at the write boundary (`apply_evolution`, → `400 PROMPT_INJECTION_BLOCKED`) + human reason string + atomic (`os.replace`) crash-safe write |
| Corpus | Chunk sanitization at index time via `sanitizer.py` |
| Model Weights | Trusted/verified sources only. Safetensors strongly preferred. `torch.load(..., weights_only=True)` alone was insufficient on torch<2.6 (CVE-2025-32434). We pin torch==2.6.0+cpu and keep loading paths (embeddings.py) minimal + documented. |

---

## Dropbox Corpus Sync (v1.4.0)

CyClaw v1.4.0 introduces **optional, out-of-band corpus synchronization** from Dropbox. The `sync/` module is a thin, security-preserving wrapper around the `rclone` binary.

**Core guarantees (all five invariants remain intact):**
- **Never touches the request path**: `gate.py`, `graph.py`, and the MCP server do **not** import anything from `sync/`. Sync runs as a completely separate process (`python -m sync.cli sync`).
- **Default one-way pull** (rclone `copy`): safest for a governed RAG corpus. Bidirectional `bisync` is opt-in and discouraged.
- **Soul & secrets protected**: `data/personality/`, `*.db*`, venvs, indices, logs, and `.git` are excluded by default via hardened filters.
- **Full audit integration**: Every added or modified file under `data/corpus/` receives a SHA-256 hash entry in the same `logs/audit.jsonl` used by the gateway.
- **Zero new Python dependencies**: Only stdlib + existing PyYAML. `rclone` (≥ v1.68.2) is an external binary you install once, like LM Studio.
- **Config-driven but secret-free**: The `sync:` block in `config.yaml` contains only paths, remote name, schedule, and safety fuses (`max_delete`, `max_transfer`). The Dropbox refresh token lives exclusively in your user-owned `rclone.conf`.

**Quick start**
1. Install rclone ≥1.68.2 and create an App-Folder-scoped Dropbox remote.
2. Add the `sync:` block to your `config.yaml` (see example in docs/SYNC_README.md).
3. Run `python -m sync.cli sync` manually or schedule it (cron / systemd / Task Scheduler / launchd).
4. Optional: `reindex_on_change: true` will exit with code 10 when the corpus changes so your indexer can react.

Full installation, configuration, security rationale, filter generation, and scheduler recipes live in **[docs/SYNC_README.md](docs/SYNC_README.md)**. The design deliberately keeps corpus mutation *outside* the LangGraph topology and soul governance path.

---

## MCP Server

For Claude Desktop or other MCP-compatible clients:

```json
{
  "mcpServers": {
    "cyclaw": {
      "command": "python",
      "args": ["/path/to/CyClaw/mcp_hybrid_server.py"]
    }
  }
}
```

The MCP server exposes a single `hybrid_search` tool. It has **no sampling capability** — `sampling: null` is set at the protocol level, making it architecturally impossible for this server to invoke an LLM.

---

## Agentic Layer (v1.5.0 — optional, disabled by default)

v1.5.0 introduces an **experimental, opt-in agentic layer** (`agentic/`) modeled 1:1 on the same out-of-band precedent as `sync/`. It extracts transferable *patterns* from modern agentic tooling — not autonomy — and maps them to safe extension points.

**All five security invariants hold by construction (enforced *and* unit-tested):**
- **Never touches the request path**: `gate.py`, `graph.py`, and the MCP server do **not** import anything from `agentic/`. `tests/test_agentic_isolation.py` asserts this.
- **Disabled by default**: `config.yaml` → `agentic.enabled: false`. Nothing runs unless explicitly enabled.
- **Read-only GitHub context** via the `gh` CLI — argv-list (never `shell=True`), `shutil.which` resolution, version floor, fully audited. CyClaw forwards **no token**; `gh` owns its own credential.
- **Governed skills registry** reuses the soul `propose/apply` pattern: injection scan at the write boundary, human reason required, atomic `tmp`+`os.replace` write, SHA-256 versioning, and a `governance_score(name) -> int` (0–100).
- **Write scaffold is DISABLED + STUBBED**: `EXECUTION_ENABLED = False`; the executor raises `NotImplementedError`. Enabling real writes is deliberately a future, separately-reviewed change.
- **Zero new runtime dependencies** (`gh` is external, like `rclone`) — CI / pip-audit / OSV surface unchanged.

The memory lifecycle is also now exposed as reusable **LangGraph nodes** (`.claude/skills/memory-orchestrator/memory_nodes.py`: `extract → consolidate → title → next_action`) while `orchestrate.py` remains a thin, 100%-backward-compatible CLI + hook shim.

---

## Containerized Deployment (v1.5.0)

```bash
docker compose up --build      # boots the FastAPI gateway on :8000, non-root, telemetry-killed
```

The `Dockerfile` is a multi-stage, non-root (`uid 1000`), `python:3.12-slim` build installing via `uv` (with a pinned `pip -c constraints.txt` fallback). `docker-compose.yml` mounts `data/`, `checkpoints/`, and `logs/` as volumes, sets `no-new-privileges`, and references a seccomp profile under `deploy/seccomp/`. Offline-first env (`CYCLAW_OFFLINE=1`, `CYCLAW_TELEMETRY_KILL=1`) is baked in.

---

*Built by [Chris Grady](https://cgfixit.com) · [cgfixit.com/linkedin](https://cgfixit.com/linkedin)*
