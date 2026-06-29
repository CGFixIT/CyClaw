---
name: cyclaw-command-run
description: >-
  CyClaw repository skill adapted from .claude/commands/run.md. Use when working in CGFixIT/CyClaw and the user asks for this Claude command workflow: Run the CyClaw smoke test suite. Starts the server if needed, executes all 6 smoke checks, and reports pass/fail with endpoint details.
---

# Cyclaw Command Run

Imported from `.claude/commands/run.md` for Codex use in this repository. Do not edit the `.claude` source files when updating this Codex adapter; update this `.codex/skills` copy instead unless the user explicitly asks otherwise.

Use Codex-native tools for Claude tool names when following the original instructions:

- `Glob` -> `rg --files` or PowerShell file enumeration
- `Grep` -> `rg`
- `Read` -> file reads through available shell or editor tools
- `Bash` -> `functions.shell_command`, respecting this session sandbox and approval rules
- Claude subagents/commands -> Codex skills, tool discovery, or normal Codex workflow as available

Do not run command-like steps from this imported workflow unless the user explicitly asks to run them.

## Original Claude Instructions

Run the CyClaw smoke test against the local server.

## Steps

1. Verify prerequisites exist:
   - `index/chroma_db/` directory
   - `index/bm25.json` file
   - `data/personality/soul.md` file
   If any are missing, stop and report what needs to be built first.

2. Execute the smoke script:
   ```bash
   bash .claude/skills/run-cyclaw/smoke.sh
   ```

3. Report results for all 6 checks:
   - `GET /health` — index_ready + graph_ready
   - `POST /query` — vault-miss path (needs_confirm=true)
   - `POST /query` with `user_confirmed_online=false` — offline_best_effort node
   - Prompt injection blocked → HTTP 400
   - `GET /soul` — personality endpoint
   - `GET /static/terminal.html` — static UI

4. Exit summary:
   - ✅ All checks passed — server is healthy
   - ❌ N checks failed — list each failure with the actual vs expected response

## Notes

- `status: degraded` in `/health` is **normal** without LM Studio running. `index_ready` and `graph_ready` are the meaningful fields.
- `needs_confirm: true` on `/query` is **correct** behavior when retrieval score is below `min_score` (0.028).
- `TELEMETRY KILL` messages on stdout are intentional.
- `GROK_API_KEY=dummy` is sufficient for all offline smoke checks.
- `soul.md` is backed up and restored by the smoke script — your personality file is never modified.

For full server setup instructions see `.claude/skills/run-cyclaw/SKILL.md`.
