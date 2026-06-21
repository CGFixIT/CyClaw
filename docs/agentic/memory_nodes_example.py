"""Tiny example: using the new memory_nodes in a LangGraph.

This is a minimal, self-contained demonstration (not production code).
It shows how extract / consolidate / next_action nodes can be wired
into a StateGraph while still respecting governance via SkillRegistry.

Run with: python -m docs.agentic.memory_nodes_example
"""

from __future__ import annotations

from typing import TypedDict, Any

from langgraph.graph import StateGraph, END

# Import the nodes we just extracted
try:
    from cyclaw.memory_orchestrator.memory_nodes import (
        extract_node,
        consolidate_node,
        next_action_node,
    )
except ImportError:
    # Fallback for running directly from repo root
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from .memory_orchestrator.memory_nodes import (
        extract_node,
        consolidate_node,
        next_action_node,
    )


class MemoryState(TypedDict, total=False):
    content: str
    memory_action: str
    suggestion: str
    governance_score_suggested_skill: int
    consolidated_path: str


def build_memory_graph(registry=None):
    """Build a tiny example memory subgraph.

    In a real agent you would inject a real SkillRegistry instance
    so governance_score is populated.
    """
    graph = StateGraph(MemoryState)

    # Nodes accept optional registry for governance_score
    graph.add_node(
        "extract",
        lambda state: extract_node(state, registry=registry),
    )
    graph.add_node(
        "consolidate",
        lambda state: consolidate_node(state, registry=registry),
    )
    graph.add_node(
        "next_action",
        lambda state: next_action_node(state, registry=registry),
    )

    # Simple flow: next_action decides, then extract or consolidate
    graph.set_entry_point("next_action")

    def route(state: MemoryState):
        action = state.get("next_memory_action", "extract")
        if "consolidate" in action:
            return "consolidate"
        return "extract"

    graph.add_conditional_edges("next_action", route, {
        "consolidate": "consolidate",
        "extract": "extract",
    })

    graph.add_edge("consolidate", "extract")
    graph.add_edge("extract", END)

    return graph.compile()


if __name__ == "__main__":
    print("Building example memory graph...")
    graph = build_memory_graph(registry=None)  # pass real registry in production
    print("Graph compiled successfully.")
    print("Nodes:", list(graph.nodes.keys()))
    print("\nExample usage in a larger agent: add this subgraph as a node or use the individual nodes.")
