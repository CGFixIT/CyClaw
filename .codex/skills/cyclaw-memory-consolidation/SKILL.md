---
name: cyclaw-memory-consolidation
description: >-
  CyClaw repository skill adapted from .claude/skills/memory-consolidation/SKILL.md. Use when working in CGFixIT/CyClaw and the user asks for this Claude skill workflow: Run a semantic "dream" consolidation over docs/memories/ — merge paraphrases, resolve contradictions, prune stale entries, and rewrite the CONSOLIDATED.md working set. Use when asked to consolidate, deduplicate, or clean up memory. Invoked by the memory-orchestrator before context compaction, on session end, and on the 12h timer.
---

# Cyclaw Memory Consolidation

Imported from `.claude/skills/memory-consolidation/SKILL.md` for Codex use in this repository. Do not edit the `.claude` source files when updating this Codex adapter; update this `.codex/skills` copy instead unless the user explicitly asks otherwise.

Use Codex-native tools for Claude tool names when following the original instructions:

- `Glob` -> `rg --files` or PowerShell file enumeration
- `Grep` -> `rg`
- `Read` -> file reads through available shell or editor tools
- `Bash` -> `functions.shell_command`, respecting this session sandbox and approval rules
- Claude subagents/commands -> Codex skills, tool discovery, or normal Codex workflow as available

Do not run command-like steps from this imported workflow unless the user explicitly asks to run them.

## Original Claude Instructions

# memory-consolidation

Run a "dream" consolidation pass over the CyClaw memory directory, `docs/memories/`, to produce a clean, non-redundant working set in `docs/memories/CONSOLIDATED.md`.

This is the *semantic* consolidation that goes beyond the orchestrator driver's structural dedupe. The driver (`orchestrate.py consolidate`) already merges identical lines and groups by section; your job is the reasoning the driver can't do — collapsing paraphrases, resolving contradictions, and pruning.

## Phase 1 — Orient

- List `docs/memories/` (snapshots, `CONSOLIDATED.md`, `INDEX.md`).
- Read `INDEX.md` and `CONSOLIDATED.md`.
- Skim recent timestamped snapshots to understand current memory state.

## Phase 2 — Gather Recent Signal

- Pull new information worth persisting from the newest snapshots.
- Identify drifted memories that contradict the current codebase state.
- Search snapshots narrowly (grep with targeted queries) for overlooked details.

## Phase 3 — Consolidate

- Rewrite `docs/memories/CONSOLIDATED.md` by merging new signal into existing entries — collapse near-duplicates and paraphrases the structural pass left behind.
- Convert any relative dates ("yesterday", "last week") to absolute dates.
- Delete facts contradicted by fresher evidence.

## Phase 4 — Prune and Index

- Run `python3 .claude/skills/memory-orchestrator/orchestrate.py consolidate` afterward so `INDEX.md` and the timer state refresh, or update `INDEX.md` by hand.
- Remove stale or dangling pointers.
- Shorten verbose entries without losing essential meaning.
- Resolve any remaining contradictions between entries.

## Constraints

- Prefer fewer, stronger memories over many weak ones.
- Merge overlapping entries by evidence strength and recency.
- Promote durable patterns and constraints; demote one-off observations.
- Edit only files under `docs/memories/`.

## Format

Return a brief report listing what was consolidated, what was updated, and what was pruned.
