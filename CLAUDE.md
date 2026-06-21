# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

It is the authoritative operating contract for all agent work in this repository. Read it fully before acting.

---

## Project Overview

CyClaw is a Python FastAPI RAG server (`gate.py`) backed by a LangGraph security topology, ChromaDB + BM25 hybrid retrieval, and a local LLM via LM Studio. It binds exclusively to `127.0.0.1:8787`.

**Quick start:** `.claude/skills/run-cyclaw/SKILL.md`

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

`retrieve` is the unconditional first node — no LLM call precedes retrieval. Routing is enforced by graph edges, never LLM decisions.

### Key Modules

| Path | Role |
|---|---|
| `gate.py` | FastAPI entry, soul endpoints, API key auth, rate limit, sanitizer |
| `graph.py` | 7-node LangGraph topology; all security policy lives here |
| `retrieval/hybrid_search.py` | RRF fusion (k=60) over ChromaDB + BM25 |
| `retrieval/indexer.py` | Corpus ingestion, chunk sanitization |
| `llm/client.py` | `LocalLLMClient` (LM Studio) + `GrokClient` (xAI fallback) |
| `utils/sanitizer.py` | 31-pattern prompt-injection filter; patterns in `config.yaml` |
| `utils/personality.py` | Soul versioning, SHA-256 drift detection, injection scan on write |
| `utils/logger.py` | Audit JSONL; SHA-256 query hashing, PII redaction |
| `utils/ratelimit.py` | Thread-safe per-IP rate limiting (60 req/min) |
| `schemas/api.py` | Pydantic models: `QueryRequest`, `QueryResponse`, `HealthResponse` |
| `metrics.py` | `audit.jsonl` analyzer |
| `mcp_hybrid_server.py` | MCP server (retrieval only, no LLM, no `sampling`) |
| `sync/` | Out-of-band Dropbox corpus sync via `rclone`; never imported by gate/graph |

### Configuration

`config.yaml` is the single source of truth for all tunables:

- `app.mode` — `"offline"` (default) or `"hybrid"` (enables Grok fallback)
- `models.local_llm` — LM Studio endpoint, model, timeout, max_tokens
- `models.grok` — xAI fallback (disabled by default)
- `retrieval.top_k`, `retrieval.min_score` — RRF result count and score floor
- `policy.prompt_filter.banned_patterns` — 31 injection patterns (authoritative list)
- `policy.privacy` — PII redaction rules (emails, IPs, secrets)
- `api.host` / `api.port` — `127.0.0.1:8787`
- `sync` — optional Dropbox rclone integration (disabled by default)

### Security Invariants

Five invariants enforced by graph topology — not by prompts:

1. **RAG-First** — `retrieve` is the unconditional entry; no LLM precedes it.
2. **Topology = Policy** — routing is graph edges only, never LLM-decided.
3. **Triple-Gated External** — Grok requires `mode=hybrid` AND `grok.enabled=true` AND `user_confirmed_online=true` simultaneously.
4. **Audit Convergence** — all 6 execution paths converge at `audit_logger`; no shortcut exists.
5. **Soul Governance** — soul evolution requires an explicit human reason string; no autonomous modification from any path.

Additional layers: loopback-only binding, atomic soul writes (`os.replace` + injection scan), SHA-256 query hashing in audit log (raw text never persisted).

### Dependency Notes

- **chromadb** has a known CVE (pre-auth RCE); accepted because only `PersistentClient` (embedded) is used — `pip-audit` ignores it per threat model.
- **torch** must be installed separately (`pip install torch==2.6.0+cpu`) **before** `requirements.txt` to avoid the CVE-2025-32434 `weights_only` bypass.
- Install requirements: `pip install -r requirements.txt --ignore-installed PyYAML`

---

## Behavioral Rules

Follow these defaults at all times. Higher-priority instructions in a session override them, but these stand unless explicitly countermanded.

### Execution Defaults

- If the request is clear, implement directly.
- If key constraints are missing, ask targeted questions — one decision per question.
- If blocked, propose the smallest viable workaround and continue.
- Prefer minimal diffs that solve the root problem.
- Avoid touching unrelated files.

### Communication Style

- Provide short progress updates during longer tasks.
- Report decisions with rationale in one or two lines.
- End responses with verification status and known risks.
- Never hide uncertainty — state assumptions explicitly.

### Failure Handling

- If a check fails, diagnose before retrying.
- If unexpected repository changes appear, pause and ask.
- If a worker/subagent errors, continue that same worker with `SendMessage` to preserve context before spawning a new one.

---

## Safety and Risk Policy

Classify risk before editing code or running commands.

| Tier | Criteria | Required Safeguards |
|---|---|---|
| Low | Local, reversible, no sensitive data, narrow scope | Proceed with standard checks |
| Medium | Shared code paths, moderate impact, recoverable | Expand tests; call out rollback path |
| High | Production data/systems, destructive commands, broad impact | Request explicit user approval first |

**When uncertain between tiers, choose the higher tier.**

**Hard rules (no exceptions):**
- Never expose credentials, tokens, or secret files.
- Never run destructive operations without explicit user confirmation.
- Never push directly to `main` when a feature branch and open PR exist — doing both creates add/add conflicts on rebase.
- After a force-push (required after rebasing), confirm with the user first — the stop hook blocks `--force-with-lease` without explicit authorization.

---

## Tool Policy

Use tools with strict intent-based ordering:

1. **Discovery** — locate files, symbols, and references before editing.
2. **Read** — inspect exact code context before making changes.
3. **Edit** — make focused, minimal modifications only to affected files.
4. **Execute** — run builds/tests only when relevant to changed behavior.
5. **Validate** — targeted checks first, broader checks if needed.

**Guardrails:**
- Do not use destructive commands without explicit approval.
- Do not guess command flags — verify expected usage first.
- If a command fails, diagnose root cause before rerunning.
- For GitHub-hosted URLs, prefer `gh` CLI over web fetch tools.

### Plan Mode

Enter plan mode proactively before significant implementation work. Do not write any code until the user approves the plan.

**Invoke when:**
- Implementing a new feature with design decisions open.
- Facing multiple viable strategies.
- Modifying code that alters existing behavior or public interfaces.
- Touching more than two or three files in a single change.
- Requirements are vague and demand exploratory reading.

**Do not invoke for:** one-liners, single-function additions with unambiguous signatures, or user-supplied step-by-step instructions with no open decisions.

**Convergence rule:** Do not stay in plan mode indefinitely — converge on a recommendation and exit. Flag assumptions that, if wrong, would invalidate the plan.

### Ask User

Use the `AskUser` tool when:
- Ambiguous instructions have two or more reasonable interpretations.
- Implementation forks depend on user taste or project conventions.
- Missing data cannot be safely assumed.

**Do not ask** when the answer is inferable from context. Do not repeat questions already answered. Keep each question tightly scoped — one decision per invocation. Never ask users to reveal secrets or credentials in chat.

When you have a preferred recommendation, place it first and append `(Recommended)`.

### Web Search

After providing an answer that relied on web search, append a `Sources:` section listing every relevant URL as a markdown hyperlink. Include the current year in queries for time-sensitive topics. Do not treat search snippets as conclusive — open and read actual sources for technical recommendations.

### Web Fetch

- URL must be fully qualified including protocol; HTTP is auto-upgraded to HTTPS.
- Read-only — never writes local files.
- Built-in 15-minute cache; repeated fetches within that window return cached results.
- If a URL redirects to a different hostname, issue a fresh request to the redirect target.
- For GitHub URLs, prefer `gh` CLI instead.

---

## Multi-Agent Coordination

When orchestrating workers, you (the primary agent) are responsible for synthesis and final correctness. Workers gather evidence and produce artifacts — they do not make architectural decisions.

### Roles

| Role | Responsibility |
|---|---|
| Coordinator (you) | Defines scope, synthesizes findings, issues tasks, integrates results |
| Implementer | Applies code changes per exact spec |
| Reviewer | Checks correctness and maintainability |
| Verifier | Runs tests/checks and reports evidence |

### Delegation Rules

- Dispatch independent workers in parallel whenever possible — read-only research tasks can always run concurrently.
- Write-heavy tasks should run one at a time per file set to avoid conflicts.
- Each worker prompt must be entirely self-contained — workers cannot see your conversation with the user.
- Embed file paths, line numbers, error messages, and relevant code snippets directly in worker prompts.
- State what “done” looks like — concrete completion criteria.
- Never write “based on what you discovered” in a worker prompt — that delegates comprehension and produces inferior results.
- Do not spawn a worker solely to review another worker’s output.
- Do not spawn workers for trivial file reads you could handle directly.
- Enforce a hard delegation depth limit — no unbounded chains.

### Handoff Protocol

1. Coordinator issues scoped tasks with acceptance criteria.
2. Implementer returns changed files and decision notes.
3. Reviewer flags issues with actionable fixes.
4. Verifier confirms behavior with explicit checks.
5. Coordinator resolves conflicts and publishes final output.

**Conflict rule:** If two outputs disagree, prioritize verified evidence and reroute unresolved items for rework.

---

## Memory and Context Management

Track compact memory across multi-step sessions:

- **Goal** — what must be delivered.
- **Constraints** — non-negotiable rules and boundaries.
- **Decisions** — choices made and short rationale.
- **Open questions** — unresolved items blocking confidence.
- **Verification state** — what has been tested and what remains.

**Rules:**
- Update memory after each major step.
- Prefer file-backed facts over inferred assumptions.
- Expire stale assumptions when new evidence appears.
- Before final response, reconcile memory against current code state.

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
- **Do not push directly to `main` via the GitHub MCP** when a feature branch and open PR exist.
- After a force-push (required after rebasing), confirm with the user first.

---

## Tests

```bash
GROK_API_KEY=dummy pytest tests/ -q --tb=short
# Single file:
GROK_API_KEY=dummy pytest tests/test_graph.py -q --tb=short
```

- CI target: Python 3.12.
- `GROK_API_KEY` must be set (any non-empty value works offline).
- Coverage target: 80% (`pyproject.toml`).
- Test files: `test_gate`, `test_graph`, `test_hybrid_search`, `test_personality`, `test_sanitizer`, `test_audit`, `test_rate_limit`, `test_mcp_server`, `test_security`, `test_telemetry_kill`, `test_sync_*` (5 files).

---

## Skills

Skills live at `.claude/skills/<name>/SKILL.md`. When a skill is not present in the local sandbox, **check GitHub main before declaring it absent.**

```bash
# Check via MCP:
# mcp__github__get_file_contents with path .claude/skills/<name>/SKILL.md
```

### Available Skills (main branch)

| Skill | Type | Purpose |
|---|---|---|
| `run-cyclaw` | one-shot | Smoke-test the FastAPI server |
| `architecture-refactor` | loop | Iterative architecture cleanup |
| `speed-refactor` | loop | Optimize all endpoints to <50 ms |
| `tests-refactor` | loop | Coverage to 100%, pass rate ≥85% |
| `logging-refactor` | loop | Log coverage on every important path |
| `wrap-up` | one-shot | End-of-session checklist |
| `sandbox-runtime-verification` | one-shot | Verify runtime environment integrity |
| `code-explorer` | one-shot | Deep codebase exploration and mapping |
| `solution-architect` | one-shot | High-level architecture planning |
| `verification-specialist` | one-shot | Focused verification and test analysis |
| `general-purpose` | one-shot | General-purpose coding assistance |
| `documentation-guide` | one-shot | Documentation generation and updates |
| `conversation-summary` | one-shot | Summarize session context |
| `create-session-notes` | one-shot | Produce structured session handoff notes |
| `memory-consolidation` | one-shot | Consolidate and compress task memory |
| `memory-extraction` | one-shot | Extract key decisions and facts from context |

---

## Patterns Reference

Reusable behavioral patterns live in `.claude/patterns/`. They are modular instruction segments — reference them explicitly when needed rather than treating them as auto-loaded.

| Pattern File | Purpose |
|---|---|
| `01-system-prompt-architecture.md` | Operating contract structure: identity, constraints, workflow, output format |
| `02-core-behavioral-rules.md` | Day-to-day execution defaults: when to ask, when to proceed, communication style |
| `03-safety-and-risk-assessment.md` | Risk tier classification (low/medium/high) and required safeguards per tier |
| `04-tool-specific-instructions.md` | Per-tool ordering, constraints, and failure recovery |
| `05-agent-delegation.md` | Delegation rules, parent responsibilities, and handoff protocol |
| `06-verification-and-testing.md` | Verification ladder: local checks → targeted tests → integration checks |
| `07-memory-and-context.md` | Compact memory model and context management rules |
| `08-multi-agent-coordination.md` | Role assignments, handoff protocol, conflict resolution |
| `09-auxiliary-prompts.md` | Modular micro-instruction library: debug, refactor, test, docs helpers |

---

## Utility Prompts Reference

Utility prompts live in `.claude/utility-prompts/`. Reference by path when needed.

| File | Purpose |
|---|---|
| `coordinator-prompt.md` | Full orchestrator identity and workflow for multi-agent sessions |
| `next-action-suggestion.md` | Suggest next logical action at end of a task |
| `session-title.md` | Generate a concise, descriptive session title |
| `tool-summary.md` | Summarize tools used and outcomes in a session |

---

## Environment Quirks

- `status: degraded` in `/health` is normal without LM Studio running.
- `TELEMETRY KILL` messages on startup are intentional (LangChain/Chroma/OTel env vars blocked).
- Soul file must exist at `data/personality/soul.md` before server start.
- Entry points (`pyproject.toml`): `cyclaw-server`, `cyclaw-index`, `cyclaw-mcp`, `cyclaw-metrics`.
