#!/usr/bin/env python3
"""CyClaw memory orchestrator — deterministic driver for the memory lifecycle.

This script owns the *mechanical* half of memory management.

In feature/CyClaw-Agent the core logic has been extracted into
memory_nodes.py so the functions are usable as first-class LangGraph nodes
while this CLI + hook interface remains 100% backward compatible.

Trigger matrix, subcommands, and behavior are unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Import the new node implementations (logic is now shared)
from .memory_nodes import (
    extract_node,
    consolidate_node,
    title_node,
    next_action_node,
    _timestamped_path,
    _save_state,
    _refresh_index,
    _load_state,
    _now,
    CONSOLIDATION_INTERVAL_HOURS,
)

# Re-export the original helper for any external code that imported it
# (keeps backward compat for anything doing "from orchestrate import ...")
from .memory_nodes import _snapshots, _split_sections  # type: ignore


# ── CLI wrappers that call the nodes (or original logic for hooks) ──────────

def cmd_path(_args) -> int:
    print(_timestamped_path())
    return 0


def cmd_extract(args) -> int:
    state = {}
    if args.content_file:
        state["content_file"] = args.content_file
    # For stdin content we still handle here for CLI ergonomics
    if not args.content_file and not sys.stdin.isatty():
        state["content"] = sys.stdin.read()

    result = extract_node(state)
    print(f"[memory] extracted -> {result.get('memory_extracted_path')}", file=sys.stderr)
    return 0


def cmd_consolidate(_args) -> int:
    result = consolidate_node({})
    print(
        f"[memory] consolidated -> {result.get('consolidated_path')} "
        f"({result.get('snapshot_count')} snapshots, {result.get('unique_lines')} lines)",
        file=sys.stderr,
    )
    return 0


def cmd_auto(args) -> int:
    rc = cmd_consolidate(args)
    if rc != 0:
        return rc
    return cmd_extract(args)


def cmd_timer_check(_args) -> int:
    state = _load_state()
    last = state.get("last_consolidation")
    due = True
    if last:
        try:
            elapsed = _now() - __import__("datetime").datetime.fromisoformat(last)
            due = elapsed.total_seconds() >= CONSOLIDATION_INTERVAL_HOURS * 3600
        except Exception:
            due = True
    if due:
        print(f"DUE (interval {CONSOLIDATION_INTERVAL_HOURS}h; last={last or 'never'})")
    else:
        print(f"NOT DUE (last={last})")
    return 0


# Hook handling still uses the original deterministic path for reliability
_EXTRACT_INSTRUCTION = (
    "Memory orchestrator: before this context is compacted, run the "
    "memory-extraction skill now. Get the target path from "
    "`python3 .claude/skills/memory-orchestrator/orchestrate.py path` and write "
    "the snapshot directly to it. A deterministic consolidation has already run. "
    "Keep it brief; capture durable user preferences, project patterns, error "
    "corrections, and workflow notes from the recent messages only."
)

def cmd_hook(_args) -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        event = {}
    name = event.get("hook_event_name", "")

    if name == "PreCompact":
        cmd_consolidate(_args)
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreCompact",
                "additionalContext": _EXTRACT_INSTRUCTION,
            }
        }
        print(json.dumps(out))
        return 0

    if name == "SessionEnd":
        cmd_consolidate(_args)
        print("[memory] SessionEnd: deterministic consolidation complete.", file=sys.stderr)
        return 0

    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CyClaw memory orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("path", help="print next snapshot path")

    p_ex = sub.add_parser("extract", help="persist a memory snapshot")
    p_ex.add_argument("--content-file", help="read snapshot content from this file")

    sub.add_parser("consolidate", help="merge/dedupe snapshots")

    p_auto = sub.add_parser("auto", help="consolidate then extract")
    p_auto.add_argument("--content-file", help="read snapshot content from this file")

    sub.add_parser("timer-check", help="is consolidation due?")
    sub.add_parser("hook", help="route a Claude Code hook event from stdin")

    args = parser.parse_args(argv)
    return {
        "path": cmd_path,
        "extract": cmd_extract,
        "consolidate": cmd_consolidate,
        "auto": cmd_auto,
        "timer-check": cmd_timer_check,
        "hook": cmd_hook,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
