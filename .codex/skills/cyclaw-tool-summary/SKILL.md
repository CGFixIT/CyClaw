---
name: cyclaw-tool-summary
description: >-
  CyClaw repository skill adapted from .claude/skills/tool-summary/SKILL.md. Use when working in CGFixIT/CyClaw and the user asks for this Claude skill workflow: Compose a brief label describing what recent tool calls accomplished. Use when asked to summarize tools used, describe recent actions, or produce a compact activity label for the UI or logs.
---

# Cyclaw Tool Summary

Imported from `.claude/skills/tool-summary/SKILL.md` for Codex use in this repository. Do not edit the `.claude` source files when updating this Codex adapter; update this `.codex/skills` copy instead unless the user explicitly asks otherwise.

Use Codex-native tools for Claude tool names when following the original instructions:

- `Glob` -> `rg --files` or PowerShell file enumeration
- `Grep` -> `rg`
- `Read` -> file reads through available shell or editor tools
- `Bash` -> `functions.shell_command`, respecting this session sandbox and approval rules
- Claude subagents/commands -> Codex skills, tool discovery, or normal Codex workflow as available

Do not run command-like steps from this imported workflow unless the user explicitly asks to run them.

## Original Claude Instructions

Compose a brief label describing what the tool calls accomplished.

## Rules

- This label appears as a single-line row in the UI and truncates around 30 characters — treat it like a git commit subject.
- Use past tense verb + the most distinctive noun from the operation.
- Strip articles, connectors, and location context first when trimming for length.

## Examples

- "Searched in auth/"
- "Fixed NPE in UserService"
- "Created signup endpoint"
- "Read config.json"
- "Ran failing tests"

## Format

One short phrase. No trailing punctuation. No explanation.
