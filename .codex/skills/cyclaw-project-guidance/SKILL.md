---
name: cyclaw-project-guidance
description: >-
  CyClaw repository operating guidance imported from CLAUDE.md and .claude rules. Use when working in CGFixIT/CyClaw to understand architecture, security invariants, commands, project rules, testing expectations, and agent workflow constraints.
---

# CyClaw Project Guidance

Use this skill before substantial work in the CyClaw repository, especially when changing `gate.py`, `graph.py`, retrieval, soul governance, sync, agentic, tests, or security-sensitive paths.

Read the relevant references before acting:

- `references/CLAUDE.md` for the authoritative repository operating contract, architecture map, invariants, commands, and skill list.
- `references/PROJECT_RULES.md` for scoped non-negotiable constraints, test commands, isolation rules, git workflow, and risk tiers.
- `references/CLAUDE-README.md` for the `.claude/` workflow structure and common command entry points.

Preserve these project invariants when adapting Claude instructions to Codex: RAG-first retrieval, topology-enforced policy, triple-gated external fallback, audit convergence, and explicit human reason strings for soul mutation.