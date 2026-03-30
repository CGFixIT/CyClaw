### https://cgfixit.com/zSafeClaw/!!!!!PyCla-3.29.36/PsyClaw/
- Currently shows latest changes i confirmed working locally on ny hpe proloant at home (will add code here and add readme, etc to properly describe the project of PsyClaw (was safeclaw until i found a repo here named that; essentially its openclaw inspired but python based using langraph for security, chromadb+BM25+RRF for RAG retrieval via mini-lm/sentencetransformers - and a custom soul file that is under data/personality (also logs daily insights for "memory"/"learning") - outside the offline mcp rag its connected to lmstudio using qwen 8b instruct and even thats a bit heavy for my server with lots of cpu and ram not much / no real gpu (when i add the demo video youll see what i mean but imagine that running on a solid graphics card compatible with cuda or a gpu proper; not worth the money fir me until i have good enough app for it and i dont trust cloud or the lack of cobtrol abd malware infested clawhub so this is like the v0.2 of PsyClaw

## Status:
- working prototype locally; next update will have terminal.html integrated - https://cgfixit.com/zSafeClaw/ contains the build before adding my version of "soul" and persistent memory via sqllite memory checkpointers but i may re-visit using sqllite depending on how it scales

PsyClaw (SafeClaw) is an early-stage **v0.1 prototype**. It is already usable as a
local RAG gateway but the API and internals may change.

What works today:

- ✅ RAG-first pipeline (ChromaDB + BM25 + RRF) over `.md` / `.txt` corpus
- ✅ FastAPI `/query` endpoint with LangGraph controller and score gate
- ✅ Local LLM via LM Studio (Qwen/Llama GGUF) for grounded answers
- ✅ Optional Grok fallback, gated by config **and** per-query user confirmation
- ✅ MCP server exposing retrieval-only tools (no sampling / no LLM in MCP)
- ✅ Audit logging (`audit.jsonl`) and basic metrics script

What this project is **not** (yet):

- ❌ General “do anything” agent
- ❌ Full-featured chat UI
- ❌ Production-hardened security product (no external audit)

Treat this as a reference implementation / lab project you can read, run,
and adapt at your own risk.

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
