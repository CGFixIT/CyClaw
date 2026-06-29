---
name: cyclaw-next-action-suggestion
description: >-
  CyClaw repository skill adapted from .claude/skills/next-action-suggestion/SKILL.md. Use when working in CGFixIT/CyClaw and the user asks for this Claude skill workflow: Suggest the single highest-value next action after completing a task or at the end of a session. Use when asked "what should I do next?", "what's next?", "next steps?", or to surface a logical continuation point.
---

# Cyclaw Next Action Suggestion

Imported from `.claude/skills/next-action-suggestion/SKILL.md` for Codex use in this repository. Do not edit the `.claude` source files when updating this Codex adapter; update this `.codex/skills` copy instead unless the user explicitly asks otherwise.

Use Codex-native tools for Claude tool names when following the original instructions:

- `Glob` -> `rg --files` or PowerShell file enumeration
- `Grep` -> `rg`
- `Read` -> file reads through available shell or editor tools
- `Bash` -> `functions.shell_command`, respecting this session sandbox and approval rules
- Claude subagents/commands -> Codex skills, tool discovery, or normal Codex workflow as available

Do not run command-like steps from this imported workflow unless the user explicitly asks to run them.

## Original Claude Instructions

Recommend the single highest-value next action the user could take.

## Rules

- Ground the suggestion in conversation context and whatever was just accomplished.
- The recommendation must be specific and immediately actionable — not a generic platitude.
- Consider what naturally follows from the work that was completed.
- Identify the current bottleneck or logical continuation point.
- Ensure the action is executable right now given the current state.

## Format

One concise, direct suggestion. No preamble, no alternatives, no hedging.
