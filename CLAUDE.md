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

Available skills (all on `main`):

| Skill | Type | Purpose |
|---|---|---|
| `/run-cyclaw` | one-shot | Smoke-test the FastAPI server |
| `/architecture-refactor` | loop | Iterative architecture cleanup |
| `/speed-refactor` | loop | Optimize all endpoints to <50 ms |
| `/tests-refactor` | loop | Coverage to 100%, pass rate ≥85% |
| `/logging-refactor` | loop | Log coverage on every important path |
| `/wrap-up` | one-shot | End-of-session checklist |

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

---

## Sandbox Runtime Verification

Skill files (`verify.sh`, `gate_runtime_check.py`) live on `main` at
`.claude/skills/sandbox-runtime-verification/` but are **not cloned into the
local sandbox** unless that commit is checked out. When the skill is invoked,
fetch the files from GitHub MCP before running:

```python
mcp__github__get_file_contents(owner="cgfixit", repo="cyclaw",
    path=".claude/skills/sandbox-runtime-verification/verify.sh", ref="refs/heads/main")
```

Write to the local path, then run. Last verified: 2026-06-20, Python 3.12.3,
**98 tests passed**.

---

## Known P0 Security Issues (open — not yet fixed in code)

Documented in `docs/CODE_SECURITY_REVIEW_2026-06-20.md`. Claude Code should
address these before next release:

1. Rate limiter race condition + missing `threading.Lock` — `gate.py`
2. ReDoS in config-driven sanitizer patterns — `utils/sanitizer.py`
3. Audit log write unprotected (crashes queries on `OSError`) — `utils/logger.py`
4. Config cache TOCTOU (no lock) — `utils/logger.py`
5. Soul preamble injected into LLM prompt without sanitization — `graph.py`

Run `/tests-refactor` after fixing to bring coverage to ≥115 tests.

---

## Test Suite Baseline (2026-06-20)

- **98 tests passing** on Python 3.12.3
- Known flaws documented in `docs/TEST_SUITE_ANALYSIS_2026-06-20.md`
- Key gap: `test_rate_limit.py` tests a private reimplementation, not `gate.py`
- Target: ≥115 tests after P0/P1 fixes from the audit doc
