---
name: cyclaw-command-wrap-up
description: >-
  CyClaw repository skill adapted from .claude/commands/wrap-up.md. Use when working in CGFixIT/CyClaw and the user asks for this Claude command workflow: End-of-session checklist. Commits work, updates memory and CLAUDE.md, applies self-improvement findings, and identifies publishable content.
---

# Cyclaw Command Wrap Up

Imported from `.claude/commands/wrap-up.md` for Codex use in this repository. Do not edit the `.claude` source files when updating this Codex adapter; update this `.codex/skills` copy instead unless the user explicitly asks otherwise.

Use Codex-native tools for Claude tool names when following the original instructions:

- `Glob` -> `rg --files` or PowerShell file enumeration
- `Grep` -> `rg`
- `Read` -> file reads through available shell or editor tools
- `Bash` -> `functions.shell_command`, respecting this session sandbox and approval rules
- Claude subagents/commands -> Codex skills, tool discovery, or normal Codex workflow as available

Do not run command-like steps from this imported workflow unless the user explicitly asks to run them.

## Original Claude Instructions

Run the end-of-session wrap-up. Delegates to the full wrap-up skill.

Load and execute `.claude/skills/wrap-up/SKILL.md` in full — all four phases in order:

1. **Ship It** — commit uncommitted changes to a `claude/wrap-up-<slug>` branch, open a draft PR. Never commit directly to `main`.
2. **Remember It** — route session learnings to the correct memory location (CLAUDE.md, `.claude/rules/`, auto memory, or `CLAUDE.local.md`).
3. **Review & Apply** — identify skill gaps, friction, and automation opportunities. Auto-apply all actionable findings.
4. **Publish It** — draft any community-relevant content from the session.

Do not skip phases. Present a consolidated report at the end.
