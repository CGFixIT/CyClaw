---
name: cyclaw-session-title
description: >-
  CyClaw repository skill adapted from .claude/skills/session-title/SKILL.md. Use when working in CGFixIT/CyClaw and the user asks for this Claude skill workflow: Generate a concise title for this session. Use when asked to title the session, name the conversation, or produce a session label for notes or memory.
---

# Cyclaw Session Title

Imported from `.claude/skills/session-title/SKILL.md` for Codex use in this repository. Do not edit the `.claude` source files when updating this Codex adapter; update this `.codex/skills` copy instead unless the user explicitly asks otherwise.

Use Codex-native tools for Claude tool names when following the original instructions:

- `Glob` -> `rg --files` or PowerShell file enumeration
- `Grep` -> `rg`
- `Read` -> file reads through available shell or editor tools
- `Bash` -> `functions.shell_command`, respecting this session sandbox and approval rules
- Claude subagents/commands -> Codex skills, tool discovery, or normal Codex workflow as available

Do not run command-like steps from this imported workflow unless the user explicitly asks to run them.

## Original Claude Instructions

Produce a concise title for this session.

## Rules

- Use 3–7 words that capture the primary topic or objective.
- Apply sentence case: capitalize only the first word and proper nouns.
- Return a JSON object with a single `"title"` field.

## Examples

Good titles:
- "Fix login button on mobile"
- "Add OAuth authentication"
- "Debug failing CI tests"

Bad titles:
- "Code changes" (too vague — says nothing specific)
- "Implementing the new user registration flow with email verification" (too long)
- "Fix Login Button On Mobile" (wrong case — title case instead of sentence case)

## Format

```json
{ "title": "Your session title here" }
```
