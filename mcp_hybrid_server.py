"""CyClaw MCP server — retrieval-only, no sampling capability.

Protocol-level guarantee: this server CANNOT invoke an LLM.
Only exposes hybrid_search tool via JSON-RPC over stdio.
User gate handled entirely in FastAPI HTTP layer.
"""

import json
import sys

from retrieval.hybrid_search import HybridRetriever
from utils.errors import RAGError
from utils.logger import audit_log

CAPABILITIES = {
    "tools": {},
    "sampling": None  # CRITICAL: No LLM path at protocol level
}

TOOLS = [
    {
        "name": "hybrid_search",
        "description": "Search local .md corpus using semantic + keyword retrieval with RRF fusion",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "top_k": {"type": "integer", "default": 5, "description": "Max results"},
                "mode": {
                    "type": "string",
                    "enum": ["hybrid", "semantic", "keyword"],
                    "default": "hybrid",
                    "description": "Retrieval mode"
                }
            },
            "required": ["query"]
        }
    }
]

def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

def _handle_search(msg_id, args: dict, retriever: HybridRetriever) -> dict:
    # DESIGN DECISION (PR #99 #12): this path intentionally does NOT run
    # utils.sanitizer.check_input. The MCP server is retrieval-only —
    # CAPABILITIES["sampling"] is None, so there is no LLM to escalate a prompt
    # injection to — and it serves a trusted local stdio caller. Prompt-injection
    # filtering here would have no escalation target to protect. If strict policy
    # parity with the HTTP path is ever desired, add check_input(query) below and
    # mirror the HTTP audit-on-block; it is omitted by design today.
    query = args.get("query", "")
    top_k = args.get("top_k", 5)
    mode = args.get("mode", "hybrid")
    try:
        if mode == "semantic":
            results = retriever.semantic_search(query, k=top_k)
        elif mode == "keyword":
            results = retriever.keyword_search(query, k=top_k)
        else:
            results = retriever.hybrid_search(query)[:top_k]
        # Audit privacy parity with the HTTP path: pass the FULL query to
        # audit_log, which SHA-256-hashes the "query" field (and redacts PII)
        # before persisting. The stored event therefore holds only query_hash —
        # never raw text — and the hash matches what the HTTP/graph audit path
        # writes for the same query. (Previously this passed query[:100], which
        # both implied cleartext and produced a hash that diverged from HTTP for
        # queries longer than 100 chars.)
        audit_log({"event": "mcp_rag_query", "query": query, "mode": mode,
                   "hit_count": len(results), "top_score": results[0].score if results else 0.0})
        payload = {
            "chunks": [{"text": r.text, "score": r.score, "source": r.source,
                        "chunk_id": r.chunk_id, "stem_tags": r.stem_tags[:5], "mode": r.retrieval_mode}
                       for r in results],
            # The response payload may echo the query — the caller already has it.
            # Only the persisted audit event is privacy-constrained.
            "metadata": {"query": query, "retrieval_mode": mode, "total_results": len(results)}
        }
        return {"jsonrpc": "2.0", "id": msg_id, "result": payload}
    except RAGError as e:
        return _error(msg_id, -32000, f"{e.code}: {e.message}")
    except Exception as e:
        return _error(msg_id, -32000, f"Search error: {str(e)}")

def handle_message(msg: dict, retriever: HybridRetriever) -> dict:
    method = msg.get("method")
    msg_id = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": "2025-11-25",
            "capabilities": CAPABILITIES,
            "serverInfo": {"name": "cyclaw-hybrid-rag", "version": "1.0.0"}
        }}
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    elif method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name")
        args = params.get("arguments", {})
        if tool_name == "hybrid_search":
            return _handle_search(msg_id, args, retriever)
        return _error(msg_id, -32601, f"Unknown tool: {tool_name}")
    elif method == "notifications/initialized":
        return None
    return _error(msg_id, -32601, f"Unknown method: {method}")

def main():
    try:
        retriever = HybridRetriever()
    except Exception as e:
        sys.stderr.write(f"[MCP] Failed to init retriever: {e}\n")
        sys.exit(1)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            response = handle_message(msg, retriever)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError as e:
            err = _error(None, -32700, f"Parse error: {str(e)}")
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
