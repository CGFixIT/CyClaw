---
name: cyclaw-command-audit
description: >-
  Codex-native CyClaw audit-log analyzer workflow. Use when working in CGFixIT/CyClaw and the user asks to audit CyClaw logs, summarize logs/audit.jsonl, run metrics.py, inspect node distribution, check retrieval score statistics, or flag audit anomalies and privacy issues.
---

# CyClaw Command Audit

Use this skill to summarize `logs/audit.jsonl` with the repository's metrics
analyzer and report anomalies without exposing private query content.

Run commands only when the user asks to execute the audit workflow. For
explanation or planning requests, inspect files and describe the workflow.

## Workflow

1. Read `AGENTS.md` for repository rules.
2. Check whether `logs/audit.jsonl` exists.
3. If it is missing, report that no audit log exists yet and that the server
   must run and receive at least one query before metrics are available.
4. If a date or time filter is requested, prefer a small, scoped JSONL filter
   before invoking `metrics.py`.
5. Run the analyzer:

```bash
GROK_API_KEY=dummy python -m metrics
```

If installed entry points are available, `cyclaw-metrics` is an equivalent
runtime path.

For date-scoped inspection, keep output bounded and avoid dumping raw audit
records into chat:

```bash
rg '"2026-06-20"' logs/audit.jsonl | GROK_API_KEY=dummy python -m metrics
```

## Report

Include:

- total queries processed
- graph node distribution
- retrieval score statistics: min, max, mean
- injection attempts blocked
- errors or unusual entries
- whether any `grok_fallback` path was triggered

Flag as risk:

- raw query text in logs, because CyClaw should store hashed query values
- error rate above 10%
- unexpected Grok fallback activity
- missing or malformed audit records

## Guardrails

- Do not paste private corpus data or raw user queries into the response unless
  the user explicitly requests that exact content and it is safe to show.
- Treat `logs/` as local runtime data; never commit audit logs.
- Respect the active Codex sandbox and approval rules for command execution.
