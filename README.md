# CyClaw

> **Offline-first, RAG-enforced, $ecure Local AI "Second Brain" (no internet required for RAG and cached Qwen7B-Instruct cached locally for RAG vault misses.)**
> Version 1.6.0 (agentic release + governed local workflows)

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-green.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.1-orange.svg)](https://github.com/langchain-ai/langgraph)
[![CodeQL Advanced](https://github.com/CGFixIT/CyClaw/actions/workflows/codeql.yml/badge.svg)](https://github.com/CGFixIT/CyClaw/actions/workflows/codeql.yml)
[![CyClaw CI (Simplified + Gated Integration)](https://github.com/CGFixIT/CyClaw/actions/workflows/ci.yml/badge.svg)](https://github.com/CGFixIT/CyClaw/actions/workflows/ci.yml)

[![Screenshots: local AI](https://i.imgur.com/kGZBkIj.png)](https://github.com/CGFixIT/CyClaw/tree/main/docs/screenshots)

---

## What It Does

CyClaw is a personal RAG (Retrieval-Augmented Generation) backend that:

1. **Answers questions exclusively from your local Markdown corpus** — no internet by default
2. **Enforces every safety invariant via LangGraph topology** — not prompts, not config flags, not discipline
3. **Maintains a persistent soul/personality layer** (`soul.md`) with SHA-256 drift detection, atomic evolution writes, and user-gated modification
4. **Falls back to Grok (xAI) only with explicit user confirmation** in hybrid mode — triple-gated at config, env, and per-query level
5. **Exposes both a FastAPI HTTP gateway and an MCP server** for Claude Desktop / Copilot Studio integration
6. **Ships optional, out-of-band operator layers** for Dropbox corpus sync (`sync/`) and agentic GitHub context / governed local workflows (`agentic/`, `.claude/`) — never imported into the request path

Zero telemetry. Binds to `127.0.0.1:8787` only. All embeddings run locally via `sentence-transformers`. No cloud dependency for offline operation. Reproducible containerized deployment via Docker is available, while agentic and sync features remain explicitly opt-in.

---

## Version History

| Version | Status | Key Changes |
|---|---|---|
| v1.2.0 | Superseded | 8 OWASP patterns, 90-day TTL, sanitizer baseline |
| v1.3.0 | **Pre-Langgrinch** | Rate limiting (60/min), 13 OWASP patterns, soul SHA-256 drift detection, atomic writes, TTL→365 days |
| v1.4.0 | Superseded | Dropbox/cloud corpus sync (out-of-band rclone wrapper + full audit integration) + requirements.txt pinned for Python 3.12 + vuln patches |
| v1.5.0 | Superseded | Out-of-band agentic layer foundations + memory orchestration nodes + Docker hardening |
| v1.6.0 | **Production (current)** | Agentic release: governed read-only GitHub context via `gh`, governed local skills registry, `.claude/` workflows/commands/patterns/tools/utility-prompts, plus README / structure refresh |

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
| Python | 3.12 | Primary supported runtime |
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

### Required local prep

```bash
mkdir -p data/personality index logs
printf '# Soul\n' > data/personality/soul.md
export GROK_API_KEY=dummy
```

### Run

```bash
python -m retrieval.indexer
uvicorn gate:app --host 127.0.0.1 --port 8787
```

Open `/` for the terminal UI and `/health` for readiness.

---

## Project Structure

```text
CyClaw/
├── gate.py
├── graph.py
├── config.yaml                 # single source of truth
├── README.md
├── Dropbox_Sync_Guide.md
├── mcp_hybrid_server.py        # retrieval-only MCP server
├── agentic/                    # out-of-band GitHub context + governed registry
│   ├── cli.py
│   ├── context.py
│   ├── gh_client.py
│   ├── registry.py
│   └── writer.py               # stubbed write scaffold, non-executing
├── .claude/                    # local operator workflows and prompts
│   ├── commands/
│   ├── hooks/
│   ├── memory/
│   ├── patterns/
│   ├── rules/
│   ├── skills/
│   ├── tools/
│   └── utility-prompts/
├── retrieval/
│   ├── indexer.py
│   ├── hybrid_search.py
│   ├── embeddings.py
│   └── stemmer.py
├── llm/
│   └── client.py
├── sync/                       # optional Dropbox corpus sync
│   ├── cli.py
│   ├── runner.py
│   └── scheduler.py
├── utils/
│   ├── sanitizer.py
│   ├── logger.py
│   ├── personality.py
│   ├── health.py
│   └── ratelimit.py
├── tests/
├── docs/
├── static/
├── data/
│   ├── corpus/
│   └── personality/
└── .github/workflows/
```

---

## Dropbox Corpus Sync

CyClaw includes an **optional, out-of-band** Dropbox sync layer that mirrors a Dropbox corpus into `data/corpus/` without touching `gate.py`, `graph.py`, or the MCP request path.

**Key capabilities**
- `rclone`-backed pull sync with safety fuses (`max_delete`, `max_transfer`)
- audit logging for changed corpus files
- optional scheduler integration for Linux and Windows
- optional reindex trigger when corpus changes

**Core commands**

```bash
python -m sync.cli test
python -m sync.cli sync --dry-run
python -m sync.cli sync
python -m sync.cli status
python -m sync.cli schedule
python -m sync.cli unschedule
```

See `Dropbox_Sync_Guide.md` for full setup and scheduling details.

---

## Agentic Layer (v1.6.0)

CyClaw now includes a **concise, governed agentic layer** for local operator workflows. It is **opt-in, disabled by default, and fully out-of-band**: it is never imported by `gate.py`, `graph.py`, or `mcp_hybrid_server.py`.

### What it adds

- **Read-only GitHub context** through the `gh` CLI
- **Governed local skills registry** with explicit human gating
- **Project workflows and operator helpers** under `.claude/`
- **Reusable local patterns** for memory, commands, tools, hooks, and utility prompts

### Security posture

- reads only in normal operation
- no GitHub token is stored or forwarded by CyClaw
- `gh` is invoked as an argv list, not via shell execution
- write behavior remains scaffolded and non-executing in the current release
- all agentic reads, refusals, and registry changes are audit logged

### Enable it

```yaml
agentic:
  enabled: true
  repo: "CGFixIT/CyClaw"
  mode: "read"
  writes_enabled: false
  gh_min_version: "2.40.0"
  registry_path: "data/agentic/skills_registry.json"
```

### Main agentic commands

```bash
python -m agentic.cli status
python -m agentic.cli context --repo
python -m agentic.cli context --pr 123
python -m agentic.cli context --issue 45
python -m agentic.cli test
python -m agentic.cli propose-skill --name deploy --desc "..." --body-file s.md --reason "draft"
python -m agentic.cli apply-skill --name deploy --desc "..." --body-file s.md --reason "add deploy runbook" --confirm
```

### `.claude/` workflows and utility surfaces

The `.claude/` tree is the local operator layer for guided workflows and reusable helper assets.

**Key areas**
- `skills/` — reusable project skills / workflows
- `commands/` — shortcut command entry points
- `patterns/` — repeatable operating patterns
- `tools/` — tool wrappers and helper definitions
- `utility-prompts/` — reusable operator prompts
- `memory/` — memory-oriented helpers / artifacts
- `hooks/` and `rules/` — local guardrails and automation boundaries

**Examples from the current repo**
- run / smoke-test workflows for CyClaw
- architecture, tests, logging, and speed refactor loops
- wrap-up / session-end workflows
- memory orchestration support patterns

### Patterns and tool-call model

Use the agentic layer for:
- repo context gathering
- PR / issue inspection
- governed local skill proposals
- human-reviewed workflow execution support

Do **not** use it to bypass CyClaw's core RAG-first runtime or to inject autonomous write paths into the gateway.

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

The MCP server exposes a retrieval-only `hybrid_search` tool. It has **no sampling capability** and is intentionally isolated from the agentic and Dropbox corpus sync layers.

---

## Security Model

| Layer | Mechanism |
|---|---|
| Network | Binds `127.0.0.1:8787` — no external exposure by design |
| Input | Config-driven injection filter (`policy.prompt_filter`) |
| Rate limit | 60 req/min per IP |
| Telemetry | Kill block runs before any SDK import in `gate.py` |
| Audit | All paths log SHA-256 query hash + PII-redacted metadata |
| Grok gating | Triple gate: `mode=hybrid` AND `grok.enabled=true` AND `user_confirmed_online=true` |
| Soul writes | Explicit human reason string + enforced write-boundary scan + atomic write |
| Agentic writes | Stubbed / non-executing in current release |

---

## Validation Commands

```bash
ruff check --select E,F,I,B,C4,S .
python -m tests.ci_rag_smoke
pytest tests/test_sanitizer.py tests/test_security.py tests/test_rate_limit.py tests/test_audit.py tests/test_client.py tests/test_personality.py
GROK_API_KEY=dummy pytest tests/test_agentic_*.py -q
python -m agentic.cli test
```

---

*Built by [Chris Grady](https://cgfixit.com) · [cgfixit.com/linkedin](https://cgfixit.com/linkedin)*
