<b>https://cgfixit.com/zSafeClaw/!!!!!PyCla-3.29.36/PsyClaw/</b> or start here and read PDF first:  
https://cgfixit.com/zSafeClaw/!!!!!PyCla-3.29.36/

## Status:
- working prototype locally; next update will have terminal.html integrated - https://cgfixit.com/zSafeClaw/ contains the build before adding my version of "soul" and persistent memory via sqllite memory checkpointers but i may re-visit using sqllite depending on how it scales

``Currently shows latest changes i confirmed working locally on ny hpe proloant at home (will add code here and add readme, etc to properly describe the project of PsyClaw (was safeclaw until i found a repo here named that; essentially its openclaw inspired but python based using langraph for security, chromadb+BM25+RRF for RAG retrieval via mini-lm/sentencetransformers - and a custom soul file that is under data/personality (also logs daily insights for "memory"/"learning") - outside the offline mcp rag its connected to lmstudio using qwen 8b instruct and even thats a bit heavy for my server with lots of cpu and ram not much / no real gpu (when i add the demo video youll see what i mean but imagine that running on a solid graphics card compatible with cuda or a gpu proper; not worth the money fir me until i have good enough app for it and i dont trust cloud or the lack of cobtrol abd malware infested clawhub so this is like the v0.2 of PsyClaw
``

```
PsyClaw v0.3 — Offline-First · RAG-First · Soul-Persistent W/ AES-256 hashed logging
============================================================

CLIENT LAYER
─────────────────────────────────────────────────────────────
  ┌──────────────────────┐   ┌─────────────────┐   ┌────────────────────┐
  │   terminal.html      │   │  CLI / Scripts  │   │ Claude Desktop /   │
  │  (Soul Console +     │   │  (HTTP / curl / │   │ LM Studio MCP      │
  │   RAG terminal UI)   │   │   PowerShell)   │   │ (JSON-RPC stdio)   │
  └──────────┬───────────┘   └────────┬────────┘   └─────────┬──────────┘
             │  HTTP                  │  HTTP                 │  MCP
             └────────────────────────┴─────────┬────────────┘
                                                 │
                                                 ▼

A. FASTAPI GATEWAY — gate.py (127.0.0.1:8787)
─────────────────────────────────────────────────────────────
  ┌─────────────────────────────────────────────────────────┐
  │                   PsyClaw Gateway v1.1                  │
  │                                                         │
  │  RAG Endpoints:          Soul Endpoints (NEW v1.1):     │
  │  ├── POST /query    ───▶  gate keeps user-confirm loop  │
  │  └── GET  /health        ├── GET  /soul                 │
  │                          ├── POST /soul/reload          │
  │  Pipeline:               ├── POST /soul/propose ──────▶ │
  │  1. Load PersonalityMgr  │     (injection scan, diff)   │
  │  2. Load HybridRetriever └── POST /soul/apply  ───────▶ │
  │  3. Build LangGraph            (write disk + SQLite)     │
  │  4. Sanitize input (banned                               │
  │     patterns, max 4000 chars)                            │
  │  5. Build GraphState{query, user_confirmed_online}       │
  │  6. Invoke graph                                         │
  └──────────────────────────────┬──────────────────────────┘
                                 │ GraphState
                                 ▼

B. LANGGRAPH CONTROLLER — graph.py (Topology = Enforcement)
─────────────────────────────────────────────────────────────
  ENTRY POINT ──────────────────────────────────────────────
       │
       ▼
  ┌──────────────────────────────────────────────────────┐
  │  Node 1: retrieve                                    │
  │  ─────────────────                                   │
  │  • HybridRetriever.hybrid_search(query)              │
  │  • Writes: retrieved_docs[], top_score, mode         │
  │  • On error → sets error flag → offline_best_effort  │
  └──────────────────────┬───────────────────────────────┘
                         │ (always)
                         ▼
  ┌──────────────────────────────────────────────────────┐
  │  Node 2: route_by_score                              │
  │  ──────────────────────                              │
  │  • Reads top_score vs cfg.retrieval.min_score(0.025) │
  │  • Sets needs_user_confirm: True / False             │
  └────────────┬───────────────────────┬─────────────────┘
               │ score >= 0.025        │ score < 0.025
               │                       │
               ▼                       ▼
  ┌────────────────────┐  ┌────────────────────────────────┐
  │  Node 3: local_llm │  │  Node 4: user_gate             │
  │  ──────────────────│  │  ─────────────────             │
  │  • soul_preamble + │  │  if user_confirmed_online=None:│
  │    retrieved_docs  │  │    → return needs_confirm=True │
  │    → LM Studio     │  │      (gateway pauses, asks     │
  │    http://127.0.0.1│  │       user to re-submit)       │
  │    :1234/v1        │  │  if True/False → route below   │
  │  • answer_model=   │  └───┬────────────────────────────┘
  │    "local"         │      │ user_confirmed_online=True
  └────────┬───────────┘      │ + hybrid + grok.enabled
           │                  ▼
           │    ┌─────────────────────────────────────────┐
           │    │  Node 5: grok_fallback                  │
           │    │  ─────────────────────                  │
           │    │  ONLY reachable when ALL true:          │
           │    │  • cfg.app.mode == "hybrid"             │
           │    │  • cfg.models.grok.enabled == true      │
           │    │  • GROK_API_KEY set in env              │
           │    │  • user_confirmed_online == True        │
           │    │  • grok.is_available()                  │
           │    │  → api.x.ai/v1  (grok-beta)            │
           │    │  → answer_model = "grok"                │
           │    └────────────────┬────────────────────────┘
           │                     │
           │    ┌────────────────▼────────────────────────┐
           │    │  Node 6: offline_best_effort            │
           │    │  ────────────────────────               │
           │    │  Used when:                             │
           │    │  • user said "no" to Grok, OR           │
           │    │  • app.mode == "offline", OR            │
           │    │  • Grok unavailable/unconfigured        │
           │    │  • soul_preamble + partial context      │
           │    │  → LM Studio (same local endpoint)      │
           │    │  → answer_model = "offline-best-effort" │
           │    └────────────────┬────────────────────────┘
           │                     │
           └──────────┬──────────┘
                      │ ALL paths converge
                      ▼
  ┌──────────────────────────────────────────────────────┐
  │  Node 7: audit_logger                               │
  │  ──────────────────────                              │
  │  • hash_query(query) → SHA-256 (raw never stored)   │
  │  • Redact PII (emails, IPs, AWS keys, Slack tokens) │
  │  • Write JSONL to logs/audit.jsonl                  │
  │  • personality.record_interaction(q_hash, outcome)  │
  └──────────────────────────┬───────────────────────────┘
                             │
                            END
                             │
                             ▼
  Gateway returns QueryResponse to client:
  { answer, sources[], retrieval_mode, hit_count,
    model_used, needs_confirm, confirm_message, error }

C. SOUL GOVERNANCE — utils/personality.py (OUTSIDE GRAPH)
─────────────────────────────────────────────────────────────
  ┌─────────────────────────────────────────────────────────┐
  │  PersonalityManager — soul lives outside the graph      │
  │                                                         │
  │  FILE-AS-TRUTH:                                         │
  │  data/personality/soul.md ◄──── source of truth        │
  │                                                         │
  │  SHADOW DB:                                             │
  │  data/personality/psyclaw_soul.db (SQLite)             │
  │  ├── soul_versions  (id, sha256, content, reason, ts)  │
  │  └── interactions   (q_hash, outcome, ts) TTL=90 days  │
  │                                                         │
  │  CRASH-SAFE WRITE ORDER:                               │
  │  1. Backup soul.md → soul.md.bak                       │
  │  2. INSERT version row into SQLite                      │
  │  3. Write soul.md to disk                              │
  │  4. Update in-memory soul_core                         │
  │  (failure at any step = recoverable)                    │
  │                                                         │
  │  STARTUP DRIFT DETECTION:                              │
  │  SHA-256(soul.md on disk) vs DB latest hash            │
  │  On mismatch → insert recovery version + log forensic  │
  │                                                         │
  │  INJECTION GATING (13+ patterns, OWASP-sourced):       │
  │  POST /soul/propose runs scan BEFORE any write         │
  │  → returns diff + injection_flags count                 │
  │  POST /soul/apply writes ONLY after human review       │
  │                                                         │
  │  SOUL INJECTION (at prompt time, NOT a graph node):    │
  │  local_llm_node & offline_best_effort_node only        │
  │  → soul_preamble + "\n\n---\n\n" + [untrusted context] │
  └─────────────────────────────────────────────────────────┘

D. RETRIEVAL LAYER — retrieval/
─────────────────────────────────────────────────────────────
  Corpus:
  data/corpus/*.md, *.txt
       │
       ▼ [python -m retrieval.indexer] (batch job)
  ┌─────────────────────────────────────────────────────────┐
  │  indexer.py                                             │
  │  chunk_size=512, overlap=50, batch_size=50             │
  │  ├── sentence-transformers all-MiniLM-L6-v2 (CPU)     │
  │  │   → index/chroma_db (dim=384, cached .emb_cache/)  │
  │  └── rank-bm25 + stemmer.py (Porter, tech-tuned)       │
  │      → index/bm25.pkl                                   │
  └─────────────────────────────────────────────────────────┘
       │ Query-time (HybridRetriever.hybrid_search)
       ▼
  semantic search (Chroma, top_k=5)
       +
  keyword search (BM25, top_k=5)
       │
       ▼ RRF fusion (k=60, vector_weight=0.6, bm25_weight=0.4)
       │
  returns SearchResult[] with top_score → Node 1

E. MCP SERVER — mcp_hybrid_server.py (stdio, no sampling)
─────────────────────────────────────────────────────────────
  JSON-RPC over stdio
  Tool: hybrid_search { query, top_k?, mode? }
  sampling: null  ← protocol-level LLM lockout
  Cannot invoke local_llm or Grok by design, not config

F. MODEL LAYER
─────────────────────────────────────────────────────────────
  ┌──────────────────────┬──────────────────────────────────┐
  │  sentence-transformers│  LM Studio (local, required)    │
  │  all-MiniLM-L6-v2    │  http://127.0.0.1:1234/v1       │
  │  CPU-only, dim=384    │  model: qwen2.5-7b-instruct     │
  │  .emb_cache/          │  temp=0.3, max_tokens=2048      │
  │  (indexer + query)    │  timeout=400s                   │
  ├──────────────────────┴──────────────────────────────────┤
  │  Grok (optional, hybrid mode only)                      │
  │  https://api.x.ai/v1  model: grok-beta                 │
  │  Requires: GROK_API_KEY env + 4 additional conditions  │
  └─────────────────────────────────────────────────────────┘

PROJECT TREE
─────────────────────────────────────────────────────────────
psyclaw/
├── gate.py              FastAPI + soul endpoints
├── graph.py             LangGraph state machine
├── mcp_hybrid_server.py MCP server (retrieval-only)
├── metrics.py           Audit JSONL analyzer
├── config.yaml          Single config source
├── requirements.txt     Pinned deps
├── terminal.html        Browser UI + Soul Console
├── llm/
│   └── client.py        LocalLLMClient + GrokClient
├── retrieval/
│   ├── embeddings.py    ST wrapper
│   ├── hybrid_search.py ChromaDB + BM25 + RRF
│   ├── indexer.py       Corpus ingestion
│   └── stemmer.py       Porter stemmer (tech-tuned)
├── schemas/
│   └── api.py           Pydantic models incl. soul schemas
├── utils/
│   ├── errors.py        Typed RAGError hierarchy
│   ├── health.py        Startup health checks
│   ├── logger.py        Audit JSONL + hash_query
│   ├── personality.py   PersonalityManager (soul CRUD)
│   └── sanitizer.py     Prompt filter + PII redaction
├── data/
│   ├── corpus/          .md/.txt knowledge base
│   └── personality/
│       └── soul.md      Identity source-of-truth
└── tests/
    ├── conftest.py
    ├── test_personality.py   Soul lifecycle + injection
    ├── test_sanitizer.py
    └── test_stemmer.py
```
# Dependencies:
```
# PsyClaw v1.1 — Offline-First, RAG-First, Soul-Persistent
# Python 3.10+
# Merged from: SafeClaw v1.0 (cgfixit.com) + PsyClaw v1.1 (attached files)

# ── Core web framework ──────────────────────────────────────────
fastapi==0.110.0
uvicorn[standard]==0.27.1
pydantic==2.6.1
pyyaml==6.0.1
httpx==0.26.0

# ── LangGraph orchestration ─────────────────────────────────────
langgraph==0.2.60
langchain-core==0.3.30

# ── Retrieval stack ─────────────────────────────────────────────
chromadb==0.4.22
sentence-transformers==2.5.1
rank-bm25==0.2.2
numpy==1.26.4

# ── Soul / Personality layer (NEW in v1.1) ──────────────────────
# sqlite3 is stdlib — no pip install needed
# difflib is stdlib — no pip install needed
# hashlib is stdlib — no pip install needed

# ── Testing ─────────────────────────────────────────────────────
pytest==8.0.2
pytest-asyncio==0.23.5

# ── Optional: metrics visualization ────────────────────────────
matplotlib==3.8.3

# ── Future roadmap (not yet required) ──────────────────────────
# openai-whisper          # STT voice pipeline
# piper-tts               # TTS voice pipeline
# rapidfuzz               # Hybrid parser fuzzy matching
# dateparser              # Natural language date parsing
# nltk                    # PsySoul typo-correction learning
# vaderSentiment          # PsySoul sentiment baseline
# playwright              # Perplexity share link scraping
```

<hr>

```
PsyClaw (SafeClaw) is an early-stage **v0.1 prototype**. It is already usable as a
local RAG gateway but the API and internals may change.

What works today:

- ✅ RAG-first pipeline (ChromaDB + BM25 + RRF) over `.md` / `.txt` corpus
- ✅ FastAPI `/query` endpoint with LangGraph controller and score gate
- ✅ Local LLM via LM Studio (Qwen/Llama GGUF) for grounded answers
- ✅ Optional Grok fallback, gated by config **and** per-query user confirmation
- ✅ MCP server exposing retrieval-only tools (no sampling / no LLM in MCP)
- ✅ Audit logging (`audit.jsonl`) and basic metrics script
- ✅ Soul.md persistence without excessive context bloat
- ✅ static\Terminal.html front-end interface to enter inputs (will add more to this later but only runs on localhost by design currently)
- ✅ "Shadow database of soul evolution" - Interactions or edits to soul.md are logged and correlated with soul version history for ez auditing

Coming soon (Hopefully):
- Vision (Univeral video input/vision - Really only Grok with x videos and Gemini with YT kinda do this well but ideally an opencv/ffmpeg based picture every few seconds and then figure out whats happening haha we'll see how difficult to get at least a basic stop motion prototype that can narrate obvious low detail scenes with few changes and build from there otherwise it'd be connecting it to other tools (ie whatsapp relay, veeam api, chrome mcp, whatever really) or finding a way to make it run faster on a 10 year old HP server lol... Other than cloud or spending a ton of money (which I will do but only when there is more to this project to justify buying a GPU or some shiz)

What this project is **not** (yet):

- ❌ General “do anything” agent
- ❌ Full-featured chat UI
- ❌ Production-hardened security product (no external audit)

Treat this as a reference implementation / lab project you can read, run,
and adapt at your own risk.
```

<!--
## Roadmap

Short term (0.2.x):

- Web front end: simple single-page “terminal” UI for `/query`
- Config polish and better error messages from the gateway
- More tests around LangGraph paths and Grok gating logic
- Improved metrics and visualizations from `audit.jsonl`

Medium term (0.3.x+):

- Optional **tool nodes** (e.g., system health, Veeam/Slack APIs),
  kept behind explicit config flags and user confirmation
- More embedding and model options (different sentence-transformers,
  alternative local LLMs)
- Better corpus tooling (ingestion status, document listing, reindex UX)

Long term (0.4.x+):

- Hardening for always-on home lab / small-team use
- Documentation on threat model and deployment patterns
- Optional packaging / installer for non-developers



---


┌──────────────────────────────────────────────────────────────────────────────┐
|     --PsyClaw – Offline‑First, RAG‑First, MCP‑Exposed                        │
└──────────────────────────────────────────────────────────────────────────────┘
https://cgfixit.com/zSafeClaw
^persistent memory and "personality" coming soon just need to verify latest changes work locally
                             ┌────────────────────────────┐
                             │   User / Client Devices   │
                             │  - Browser UI (HTTP)       │
                             │  - CLI / scripts (HTTP)    │
                             │  - LM Studio UI (MCP)      │
                             └─────────────┬──────────────┘
                                           │  User query
                                           ▼

┌──────────────────────────────────────────────────────────────────────────────┐
│ A. FastAPI Gateway Layer (psyclaw/gate.py)                                   │
└──────────────────────────────────────────────────────────────────────────────┘

                         ┌────────────────────────────┐
                         │  FastAPI Gateway :8787     │
                         │  - POST /query             │
                         │  - GET  /health            │
                         │  - Input prompt filter     │
                         │  - Binds 127.0.0.1 only    │
                         └─────────────┬──────────────┘
                                       │
                             builds initial GraphState
                             { query, user_confirmed_online? }
                                       │
                                       ▼

┌──────────────────────────────────────────────────────────────────────────────┐
│ B. LangGraph Controller (psyclaw/graph.py)                                   │
│    Topology = Enforcement                                                    │
└──────────────────────────────────────────────────────────────────────────────┘

                         ┌────────────────────────────┐
                         │     LangGraph Graph        │
                         │   ("PsyClaw Clawbot")      │
                         └─────────────┬──────────────┘
                                       │
                                       ▼

   [Node 1: retrieve]
   ──────────────────
   • Reads state.query
   • Calls Hybrid Retrieval Service (Section C)
   • Writes:
       - retrieved_docs[ ] (chunks + scores)
       - top_score: float
       - retrieval_mode: "hybrid" | "vector" | "bm25" | "none"

             │
             ▼

   [Node 2: route_by_score]
   ───────────────────────
   • Compares top_score to cfg.retrieval.min_score (e.g. 0.75)
   • If top_score ≥ threshold:
   │     state.needs_user_confirm = False
   │     ──► route to local_llm
   • Else:
         state.needs_user_confirm = True
         ──► route to user_gate

             │
   ┌─────────┴───────────┐
   │                     │
   ▼                     ▼

[Node 3: local_llm]                     [Node 4: user_gate]
────────────────────                     ───────────────────
• Builds prompt from                     • If user_confirmed_online is None:
  retrieved_docs + query                   - Graph returns to gateway with:
• Calls LM Studio chat                       needs_confirm = true
  http://127.0.0.1:1234/v1                  confirm_message: "Vault miss
  with configured model                     (score X < 0.75). Go online? (y/n)"
• Writes:                                  • Client prompts user and resubmits:
    - state.answer                            { query, user_confirmed_online }
    - state.answer_model = "local"
    - state.answer_sources = top N docs

   │                                         │
   │                                         ▼

   │                         [Conditional routing from user_gate]
   │                         ────────────────────────────────────
   │                         • If:
   │                             - cfg.app.mode == "hybrid"
   │                             - cfg.models.grok.enabled
   │                             - state.user_confirmed_online is True
   │                           ──► grok_fallback
   │                         • Else
   │                           ──► offline_best
   │
   ▼

[Node 5: grok_fallback]              [Node 6: offline_best]
────────────────────────              ─────────────────────────────
• Only reachable when:               • Used when:
    - hybrid mode enabled               - user said "no", OR
    - Grok enabled                      - hybrid/online disabled
    - user_confirmed_online = True   • Generates best‑effort answer from
• Prompt:                               local LLM (with disclaimer)
    - query alone, or                • Writes:
    - query + sanitized context         - state.answer
      (if config allows)                - state.answer_model = "offline-best-effort"
• Calls Grok via xAI API                - state.answer_sources = retrieved_docs
  with GROK_API_KEY

             │
             └──────────────┬─────────────────────────────┐
                            ▼                             ▼

                      [Node 7: audit_logger]
                      ──────────────────────
                      • Runs for ALL paths (local, grok, offline)
                      • Computes query_hash = SHA256(query)
                      • Writes JSONL line to logs/audit.jsonl:
                           { event, timestamp, query_hash,
                             top_score, retrieval_mode,
                             online_escalated, model_used }
                      • Attaches state.audit
                      • Graph terminates (END)

                                       │
                                       ▼
                         ┌────────────────────────────┐
                         │   Gateway HTTP / MCP Resp  │
                         │  - answer                  │
                         │  - sources (chunks/meta)   │
                         │  - retrieval_mode          │
                         │  - hit_count               │
                         │  - model_used              │
                         │  - needs_confirm           │
                         │  - confirm_message (opt)   │
                         └────────────────────────────┘
-->
