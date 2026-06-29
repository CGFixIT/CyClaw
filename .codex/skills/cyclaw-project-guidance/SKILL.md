---
name: cyclaw-project-guidance
description: >-
  CyClaw repository operating guidance for Codex. Use when working in CGFixIT/CyClaw to understand architecture, security invariants, commands, project rules, testing expectations, agent workflow constraints, and canonical docs before substantial edits.
---

# CyClaw Project Guidance

Use this skill before substantial work in the CyClaw repository, especially when
changing `gate.py`, `graph.py`, retrieval, soul governance, sync, agentic,
tests, dependencies, CI, or security-sensitive paths.

Read the relevant references before acting:

- `references/CLAUDE.md` for the authoritative repository operating contract, architecture map, invariants, commands, and skill list.
- `references/PROJECT_RULES.md` for scoped non-negotiable constraints, test commands, isolation rules, git workflow, and risk tiers.
- `references/CLAUDE-README.md` for the `.claude/` workflow structure and common command entry points.

When the references mention Claude-specific tools, commands, or hooks, translate
them into the active Codex toolset and current sandbox/approval rules. Do not
run command steps merely because a legacy reference lists them; run them only
when they fit the user's request.

Preserve these project invariants: RAG-first retrieval, topology-enforced
policy, triple-gated external fallback, audit convergence, and explicit human
reason strings for soul mutation.
