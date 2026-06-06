"""PsyClaw MCP server — retrieval-only, no sampling capability.

Protocol-level guarantee: this server CANNOT invoke an LLM.
Only exposes hybrid_search tool via JSON-RPC over stdio.
User gate handled entirely in FastAPI HTTP layer.
"""

import sys
import json

from retrieval.hybrid_search import HybridRetriever
from utils.logger import audit_log
from utils.errors import RAGError

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
        audit_log({"event": "mcp_rag_query", "query": query[:100], "mode": mode,
                   "hit_count": len(results), "top_score": results[0].score if results else 0.0})
        payload = {
            "chunks": [{"text": r.text, "score": r.score, "source": r.source,
                        "chunk_id": r.chunk_id, "stem_tags": r.stem_tags[:5], "mode": r.retrieval_mode}
                       for r in results],
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
            "serverInfo": {"name": "psyclaw-hybrid-rag", "version": "1.0.0"}
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
