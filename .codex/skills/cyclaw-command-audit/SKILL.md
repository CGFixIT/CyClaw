---
name: cyclaw-command-audit
description: >-
  CyClaw repository skill adapted from .claude/commands/audit.md. Use when working in CGFixIT/CyClaw and the user asks for this Claude command workflow: Run metrics.py against audit.jsonl to produce a session summary — query counts, node distribution, score stats, and any anomalies.
---

# Cyclaw Command Audit

Imported from `.claude/commands/audit.md` for Codex use in this repository. Do not edit the `.claude` source files when updating this Codex adapter; update this `.codex/skills` copy instead unless the user explicitly asks otherwise.

Use Codex-native tools for Claude tool names when following the original instructions:

- `Glob` -> `rg --files` or PowerShell file enumeration
- `Grep` -> `rg`
- `Read` -> file reads through available shell or editor tools
- `Bash` -> `functions.shell_command`, respecting this session sandbox and approval rules
- Claude subagents/commands -> Codex skills, tool discovery, or normal Codex workflow as available

Do not run command-like steps from this imported workflow unless the user explicitly asks to run them.

## Original Claude Instructions

Run the CyClaw audit log analyzer. $ARGUMENTS

## Steps

1. Check the audit log exists:
   ```bash
   test -f logs/audit.jsonl && echo "EXISTS" || echo "MISSING"
   ```
   If missing: report that no audit log exists yet — start the server and make at least one query to generate it.

2. Run the metrics analyzer:
   ```bash
   GROK_API_KEY=dummy python3 -m metrics
   # or via entry point:
   cyclaw-metrics
   ```

3. If `$ARGUMENTS` contains a date or time filter (e.g. "today", "last hour", "2026-06-20"), filter the JSONL before analysis:
   ```bash
   grep '"2026-06-20"' logs/audit.jsonl | python3 -m metrics
   ```

4. Report the following from the output:
   - Total queries processed
   - Graph node distribution (which paths were exercised)
   - Retrieval score statistics (min, max, mean)
   - Injection attempts blocked
   - Any anomalies or error entries

5. Flag if:
   - Any raw query text appears in the log (PII/privacy violation — should be SHA-256 hashed)
   - Error rate exceeds 10%
   - Any entries with `grok_fallback` node were triggered (means hybrid mode was active)

## Notes

- Audit log is append-only JSONL at `logs/audit.jsonl`
- Query text is SHA-256 hashed — raw queries are never stored by design
- `GROK_API_KEY` must be set even for offline metrics runs
