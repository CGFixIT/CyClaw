"""RAG performance metrics — parses audit.jsonl.

Usage:
   python metrics.py
"""

import json
from collections import Counter
from pathlib import Path

import yaml


def load_events(audit_file: str):
    events = []
    if not Path(audit_file).exists():
        return events
    with open(audit_file, encoding="utf-8") as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events

def compute_metrics(events: list) -> dict:
    """Aggregate audit events into a JSON-serializable summary.

    Returns aggregates only — never raw query text. The audit log stores
    SHA-256 query hashes (not plaintext) by design, so this summary is safe to
    expose over the API-key-gated ``GET /audit/summary`` endpoint for regulated
    SMBs that need audit evidence (query volume, external-LLM usage, score
    distribution) without leaking the underlying queries.
    """
    summary = {
        "total_events": len(events),
        "event_breakdown": {},
        "rag_query_count": 0,
        "scores": {"avg": None, "min": None, "max": None},
        "retrieval_modes": {},
        "model_used": {},
        "online_escalated": 0,
    }
    if not events:
        return summary

    event_counts = Counter(e.get("event", "unknown") for e in events)
    summary["event_breakdown"] = dict(event_counts.most_common())

    rag_queries = [e for e in events if e.get("event") in ("rag_query", "mcp_rag_query")]
    summary["rag_query_count"] = len(rag_queries)
    if rag_queries:
        scores = [e["top_score"] for e in rag_queries if "top_score" in e]
        if scores:
            summary["scores"] = {
                "avg": sum(scores) / len(scores),
                "min": min(scores),
                "max": max(scores),
            }
        # The graph audit path records the retrieval mode under "retrieval_mode";
        # the MCP server (mcp_hybrid_server._handle_search) records it under "mode".
        # Reading only "retrieval_mode" silently bucketed every mcp_rag_query as
        # "unknown" even though its mode was right there under the other key.
        mode_counts = Counter(
            e.get("retrieval_mode") or e.get("mode") or "unknown" for e in rag_queries
        )
        summary["retrieval_modes"] = dict(mode_counts.most_common())

    # model_used is only meaningful for answered queries. Scope it to rag_queries
    # (mirroring scores/modes above) so non-answer events — notably the graph
    # audit node's "user_gate_pause", which is still stamped model_used="unknown"
    # (graph.audit_logger_node) — don't pollute the model-usage breakdown shown at
    # GET /audit/summary with a bogus "unknown" bucket.
    model_counts = Counter(e["model_used"] for e in rag_queries if e.get("model_used"))
    summary["model_used"] = dict(model_counts.most_common())

    # An escalation to the external LLM. Prefer the explicit boolean the graph
    # audit node already records (audit_logger_node sets
    # online_escalated = answer_model == "grok") as the source of truth; fall back
    # to user_confirmed_online / the model-name heuristic for older or MCP events
    # that predate the explicit field. Relying on user_confirmed_online alone
    # undercounted real escalations because the graph never writes that key.
    summary["online_escalated"] = sum(
        1
        for e in events
        if e.get("online_escalated") is True
        or e.get("user_confirmed_online") is True
        or str(e.get("model_used", "")).lower().startswith("grok")
    )
    return summary


def print_metrics(config_path: str = "config.yaml"):
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    audit_file = cfg["logging"]["audit_file"]
    events = load_events(audit_file)
    if not events:
        print("No audit events found.")
        return
    summary = compute_metrics(events)
    print(f"Total events: {summary['total_events']}")
    print("\nEvent breakdown:")
    for event, count in summary["event_breakdown"].items():
        print(f"  {event}: {count}")
    if summary["rag_query_count"]:
        print(f"\nRAG queries: {summary['rag_query_count']}")
        s = summary["scores"]
        if s["avg"] is not None:
            print(f"\nRAG scores — avg: {s['avg']:.3f}, min: {s['min']:.3f}, max: {s['max']:.3f}")
        if summary["retrieval_modes"]:
            print("\nRetrieval modes:")
            for mode, count in summary["retrieval_modes"].items():
                print(f"  {mode}: {count}")
        # model_used and online_escalated are computed by compute_metrics() and
        # surfaced at GET /audit/summary, but the CLI dropped them on the floor.
        # Print them so `cyclaw-metrics` shows which model answered and how many
        # queries escalated to the external (paid) LLM.
        if summary["model_used"]:
            print("\nModel used:")
            for model, count in summary["model_used"].items():
                print(f"  {model}: {count}")
        print(f"\nOnline escalations (external LLM): {summary['online_escalated']}")

def main() -> None:
    """Console entry point for ``cyclaw-metrics`` (see pyproject [project.scripts]).

    Thin wrapper over :func:`print_metrics`. The declared
    ``cyclaw-metrics = "metrics:main"`` script previously raised AttributeError
    because this module only defined ``print_metrics``, not ``main``.
    """
    print_metrics()


if __name__ == "__main__":
    main()
