# CyClaw — Claude Instructions

## Project

CyClaw is a Python FastAPI RAG server (`gate.py`) with a LangGraph security topology,
ChromaDB + BM25 retrieval, and a local LLM via LM Studio. It binds to `127.0.0.1:8787`.

Quick start: see `.claude/skills/run-cyclaw/SKILL.md`.

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
- **Do not push directly to `main` via the GitHub MCP** when a feature branch and open PR
  exist — doing both creates add/add conflicts on rebase. Commit only to the feature
  branch and let the PR merge carry changes into main.
- After a force-push (required after rebasing), confirm with the user first — the
  auto-permission classifier blocks `--force-with-lease` without explicit authorization.

---

## Skills

Skills live at `.claude/skills/<name>/SKILL.md`. When a user invokes a skill that is
not present in the local sandbox, **check GitHub main before declaring it absent**:

```bash
# or use mcp__github__get_file_contents with path .claude/skills/<name>/SKILL.md
```

Available loop skills (all on `main`):

| Skill | Purpose |
|---|---|
| `/run-cyclaw` | Smoke-test the FastAPI server |
| `/architecture-refactor` | Iterative architecture cleanup |
| `/speed-refactor` | Optimize all endpoints to <50 ms |
| `/tests-refactor` | Coverage to 100%, pass rate ≥85% |
| `/logging-refactor` | Log coverage on every important path |
| `/wrap-up` | End-of-session checklist |

---

## Tests

```bash
GROK_API_KEY=dummy pytest tests/ -q --tb=short
```

CI target is Python 3.12. `GROK_API_KEY` must be set (any non-empty value works offline).

---

## Environment Quirks

- `PyYAML` conflicts on install: use `pip install -r requirements.txt --ignore-installed PyYAML`
- `status: degraded` in `/health` is normal without LM Studio running
- `TELEMETRY KILL` messages on startup are intentional
- Soul file must exist at `data/personality/soul.md` before server start
