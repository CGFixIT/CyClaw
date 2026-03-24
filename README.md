# PsyClaw – Offline‑First, RAG‑First, MCP‑Exposed (Option C: sentence-transformers)
===========================================================================

                             ┌────────────────────────────┐
                             │   Chris / Client Devices   │
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