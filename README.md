# PsyClaw

> **Offline-first, RAG-enforced, soul-governed personal AI assistant**
> Version 1.4.0 (planning) · Baseline 1.3.0 (production) · Python 3.12 · LM Studio + ChromaDB + BM25 + LangGraph

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-green.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.1-orange.svg)](https://github.com/langchain-ai/langgraph)
[![CodeQL Advanced](https://github.com/CGFixIT/PsyClaw/actions/workflows/codeql.yml/badge.svg)](https://github.com/CGFixIT/PsyClaw/actions/workflows/codeql.yml)<hr>
[![Screenshots of local AI web app!](https://i.imgur.com/kGZBkIj.png)](https://github.com/CGFixIT/PsyClaw/tree/main/screenshots)   <-- Screenshots of Local AI web interface

---

## What It Does

PsyClaw is a personal RAG (Retrieval-Augmented Generation) backend that:

1. **Answers questions exclusively from your local Markdown corpus** — no internet by default
2. **Enforces every safety invariant via LangGraph topology** — not prompts, not config flags, not discipline
3. **Maintains a persistent soul/personality layer** (`soul.md`) with SHA-256 drift detection, atomic evolution writes, and user-gated modification
4. **Falls back to Grok (xAI) only with explicit user confirmation** in hybrid mode — triple-gated at config, env, and per-query level
5. **Exposes both a FastAPI HTTP gateway and an MCP server** for Claude Desktop / Copilot Studio integration

Zero telemetry. Binds to `127.0.0.1:8787` only. All embeddings run locally via `sentence-transformers`. No cloud dependency for offline operation.

---

## Version History

| Version | Status | Key Changes |
|---|---|---|
| v1.2.0 | Superseded | 8 OWASP patterns, 90-day TTL, sanitizer baseline |
| v1.3.0 | **Pre-Langgrinch** | Rate limiting (60/min), 13 OWASP patterns, soul SHA-256 drift detection, atomic writes, TTL→365 days |
| v1.4.0 | **Production (current)** | Updated requirements.txt to patch vulns and modernize for Python 3.12 |
| v1.5.0 | **Planning** | Fix Stemmer.py, sql write placeholder code sections, other cleanups,test Dropbox corpus sync integration, BM25 SHA Integrity Detection

---

## Architecture

```
User Query (HTTP POST /query or MCP tool call)
         │
         ▼
    ┌─────────────────────────────────────────────────────┐
    │  gate.py  (FastAPI, 127.0.0.1:8787)                 │
    │  • Rate limit (60 req/min per IP — RUNS FIRST)      │
    │  • Prompt injection filter (sanitizer.py, 13 pat.)  │
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
| 4 GB+ RAM | — | For sentence-transformers + ChromaDB in-process |

### Install

```bash
git clone https://github.com/CGFixIT/PsyClaw
cd PsyClaw
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 1) Install CPU-only torch first (keeps the install lean + offline-friendly;
#    a bare transitive install would pull the ~2.5 GB CUDA build on Linux).
pip install torch==2.4.1+cpu --index-url https://download.pytorch.org/whl/cpu

# 2) Install the rest, pinned to the verified transitive tree.
pip install -r requirements.txt -c constraints.txt
```

> **Upgrading from a pre-1.4.0 checkout?** ChromaDB moved from 0.4.x to 1.5.x and the
> on-disk index format changed — delete `index/` and rebuild with `python -m retrieval.indexer`.
>
> **Offline note:** embeddings use `all-MiniLM-L6-v2`. Because `psyclaw_telemetry_kill.env`
> sets `HF_HUB_OFFLINE=1`, the model must be cached locally first. On a machine with network,
> run the indexer once (it downloads + caches the model); afterwards it runs fully offline.

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

> **Note:** `vector_weight` / `bm25_weight` in `config.yaml` are documentation-only placeholders. The retriever uses equal 1.0/1.0 weighting — a deliberate design decision documented in the v1.3.0 architecture spec. To enable true weighted RRF, multiply `contrib *= weight` in `hybrid_search.py` and retune `min_score`.

### Set Environment (hybrid mode only)

```bash
# Required only if app.mode = "hybrid"
export GROK_API_KEY=your_xai_api_key_here

# Kill all SDK telemetry (also set automatically by gate.py on startup)
source psyclaw_telemetry_kill.env
```

### Build the Index

```bash
# Place .md / .txt files into data/corpus/
python -m retrieval.indexer
# Builds: index/chroma_db/   and   index/bm25.pkl
```

### Run

```bash
uvicorn gate:app --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787` — the Soul Console terminal loads automatically.

---

## Project Structure

```
PsyClaw/
├── gate.py                     FastAPI gateway + soul endpoints
├── graph.py                    LangGraph 7-node state machine
├── mcp_hybrid_server.py        MCP server (retrieval-only, no LLM)
├── metrics.py                  Audit JSONL analyzer
├── config.yaml                 Single source of truth for all config
├── requirements.txt            Pinned Python deps
├── psyclaw_telemetry_kill.env  Kill-switch for LangChain/Chroma/OTel telemetry
├── psyclaw_suggestions_fix.md  Dev notes and open issues
├── .gitignore
├── old.md                      Archived prior README
├── llm/
│   └── client.py               LocalLLMClient + GrokClient
├── retrieval/
│   ├── embeddings.py           sentence-transformers wrapper
│   ├── hybrid_search.py        ChromaDB + BM25 + RRF fusion
│   ├── indexer.py              Corpus ingestion + index build
│   └── stemmer.py              Porter stemmer (tech-vocabulary tuned)
├── schemas/
│   └── api.py                  Pydantic request/response models
├── utils/
│   ├── errors.py               Typed RAGError hierarchy
│   ├── health.py               Startup dependency health checks
│   ├── logger.py               Audit JSONL + SHA-256 query hashing
│   ├── personality.py          PersonalityManager (soul CRUD + governance)
│   └── sanitizer.py            Prompt injection filter + PII redaction
├── static/
├   |── extractor.html          Browser-Based simplified insight_extractor.py to generate .md corpus files
│   └── terminal.html           Browser UI / Soul Console
├── data/
│   ├── corpus/                 .md / .txt knowledge base (gitignored runtime content)
│   └── personality/
│       └── soul.md             Identity source-of-truth
└── tests/
    ├── conftest.py
    ├── test_gate.py
    ├── test_graph.py
    ├── test_hybrid_search.py
    ├── test_sanitizer.py
    ├── test_personality.py
    ├── test_personality_changes.py
    ├── test_rate_limit.py
    ├── test_audit.py
    ├── test_stemmer.py
    ├── apipsTest.ps1           Windows PowerShell smoke test
    └── cmd2index.bat           Windows index rebuild shortcut
```

---

## Soul / Personality Layer

PsyClaw maintains a persistent identity through `soul.md`. Key properties:

- **File-as-truth**: `data/personality/soul.md` is always the canonical version
- **Shadow SQLite DB**: `psyclaw_soul.db` stores version history and interaction logs
- **SHA-256 drift detection**: on startup, file hash vs. DB hash — mismatch triggers forensic log entry
- **Atomic writes**: backup → DB insert → disk write → memory update (failure at any step is recoverable)
- **OWASP injection scan**: `POST /soul/propose` runs 13 injection patterns before any write
- **Human-in-the-loop evolution**: apply only via `POST /soul/apply` after reviewing the diff

---

## Security Model

| Layer | Mechanism |
|---|---|
| Network | Binds `127.0.0.1:8787` — no external exposure by design |
| Input | 13-pattern OWASP injection filter, 4000 char max |
| Rate limit | 60 req/min per IP (in-memory sliding window) |
| Telemetry | Kill block runs before any SDK import in `gate.py` |
| Audit | All paths log SHA-256 query hash + PII-redacted metadata |
| Grok gating | Triple gate: config flag + env var + per-query confirmation |
| Soul writes | Injection scan + human reason string + atomic crash-safe write |
| Corpus | Chunk sanitization at index time via `sanitizer.py` |

> **This is a personal lab project, not a production security product.** No external audit has been performed.

---

## MCP Server

For Claude Desktop or other MCP-compatible clients:

```json
{
  "mcpServers": {
    "psyclaw": {
      "command": "python",
      "args": ["/path/to/PsyClaw/mcp_hybrid_server.py"]
    }
  }
}
```

The MCP server exposes a single `hybrid_search` tool. It has **no sampling capability** — `sampling: null` is set at the protocol level, making it architecturally impossible for this server to invoke an LLM.

---

Completed in v1.3.0

    Rate limiting (60 req/min per IP, sliding window)
    Soul SHA-256 drift detection on startup
    Atomic soul writes (backup → DB → disk → memory)
    Expanded to 13 OWASP injection patterns
    interaction_ttl_days extended to 365
    Telemetry kill block moved before any SDK import
    route_by_score threshold corrected to 0.028 (RRF scale, not cosine)
    Soul preamble injection hardened (labeled as untrusted context)

Open Issues / v1.4.0 Targets

    Dropbox corpus sync (dropbox_sync.py placeholder)
    plan_node for multi-hop query decomposition
    insightextractor.py for automated corpus enrichment from query patterns
    Conversation compaction (rolling summary node)
    BM25 index SHA-256 integrity verification on load
    static/terminal.html API alignment (currently has endpoint mismatches)
    Config schema validation on startup (pydantic model for config.yaml)
    Weighted RRF option (currently equal 1.0/1.0 by design)

Known Issues

    static/terminal.html has API response field mismatches vs current QueryResponse schema
    vector_weight/bm25_weight in config.yaml are documentation-only; actual weighting is equal
    min_score threshold comments reference cosine similarity but value is RRF scale


---

## Status & Roadmap

**What works in v1.3.0:**
- RAG-first pipeline (ChromaDB + BM25 + RRF)
- FastAPI `/query` with LangGraph 7-node controller
- Local LLM via LM Studio
- Optional Grok fallback (triple-gated)
- MCP server (retrieval-only)
- Audit JSONL with SHA-256 hashing and PII redaction
- Soul persistence with drift detection and atomic writes
- Rate limiting (60/min per IP)
- Browser UI via `static/terminal.html`

**v1.4.0 targets:**
- Dropbox/cloud corpus sync
- `plan_node` for multi-step query decomposition
- `insightextractor.py` for automated corpus enrichment
- Conversation compaction (rolling summary)
- BM25 index SHA-256 integrity check on load

**Not yet / not planned:**
- General-purpose agent (tool invocation from corpus context)
- Multi-user or network-exposed deployment
- Production security hardening (external pentest)

---

## License

*** This Application is not available for share, copy, download, or monetization [yet;)] ***

---

*Built by [Chris Grady](https://cgfixit.com) · [cgfixit.com/linkedin](https://cgfixit.com/linkedin)*
