"""RAG performance metrics — parses audit.jsonl.

Usage:
   python metrics.py
"""

import json
import os
from collections import Counter
from pathlib import Path
import yaml

def load_events(audit_file: str):
    events = []
    if not Path(audit_file).exists():
        return events
    with open(audit_file) as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events

def print_metrics(config_path: str = "config.yaml"):
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    audit_file = cfg["logging"]["audit_file"]
    events = load_events(audit_file)
    if not events:
        print("No audit events found.")
        return
    event_counts = Counter(e.get("event", "unknown") for e in events)
    print(f"Total events: {len(events)}")
    print("\nEvent breakdown:")
    for event, count in event_counts.most_common():
        print(f"  {event}: {count}")
    rag_queries = [e for e in events if e.get("event") in ("rag_query", "mcp_rag_query")]
    if rag_queries:
        scores = [e["top_score"] for e in rag_queries if "top_score" in e]
        if scores:
            print(f"\nRAG scores — avg: {sum(scores)/len(scores):.3f}, min: {min(scores):.3f}, max: {max(scores):.3f}")
        mode_counts = Counter(e.get("retrieval_mode") for e in rag_queries)
        print("\nRetrieval modes:")
        for mode, count in mode_counts.most_common():
            print(f"  {mode}: {count}")

if __name__ == "__main__":
    print_metrics()
