#!/usr/bin/env python

"""PsyClaw FastAPI Gateway — HTTP/MCP entry point.

Invokes the LangGraph controller for every query.
Handles user confirmation flow for Grok fallback at the HTTP layer.
Binds to loopback only (see api.host / api.port in config.yaml).

CHANGES FROM ORIGINAL (soul.md / persistent personality integration):
  - Initialize PersonalityManager from config if personality.enabled
  - Pass personality to build_graph()
  - Add /soul endpoint (GET current soul, POST propose evolution)
  - Add /soul/apply endpoint (POST to apply after user confirmation)

---

Addresses:
  - LangSmith phone-home via langchain-core / langgraph
  - ChromaDB PostHog anonymized telemetry
  - OpenTelemetry OTLP export hooks pulled in by chromadb deps
"""
import os
import re

_TELEMETRY_KILL = {
    "LANGCHAIN_TRACING_V2": "false",
    "LANGSMITH_TRACING": "false",
    "LANGGRAPH_CLI_NO_ANALYTICS": "1",
    "ANONYMIZED_TELEMETRY": "False",
    "CHROMA_OTEL_COLLECTION_ENDPOINT": "",
    "CHROMA_OTEL_SERVICE_NAME": "",
    "OTEL_SDK_DISABLED": "true",        # kills entire OTel SDK
    "OTEL_TRACES_EXPORTER": "none",
    "OTEL_METRICS_EXPORTER": "none",
    "OTEL_LOGS_EXPORTER": "none",
}
for k, v in _TELEMETRY_KILL.items():
    os.environ[k] = v

# Hard-remove any accidentally set API keys
for _key in ("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY", "LANGCHAIN_ENDPOINT"):
    os.environ.pop(_key, None)
    
_EXPECTED = list(_TELEMETRY_KILL.keys())
_verified = {k: os.environ.get(k, "NOT SET") for k in _EXPECTED}
print("[TELEMETRY KILL] Verified env state:")
for k, v in _verified.items():
    status = "OK" if v not in ("", "NOT SET") else "MISSING"
    print(f"  {status}  {k}={v}")

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from graph import build_graph, GraphState
from retrieval.hybrid_search import HybridRetriever
from llm.client import LocalLLMClient, GrokClient
from schemas.api import QueryRequest, QueryResponse, SourceInfo, HealthResponse, SoulEvolutionRequest
from utils.logger import audit_log
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from utils.sanitizer import check_input
from utils.errors import (
    RAGError, PromptInjectionError, IndexNotFoundError, LLMServiceError
)
from utils.health import check_all
from utils.personality import PersonalityManager

# Simple in-memory rate limiter (config-driven, per-IP for /query)
import time
from collections import defaultdict
from fastapi import Request, HTTPException as FastAPIHTTPException

_rate_limits = defaultdict(list)
RATE_LIMIT_REQUESTS = 60
RATE_LIMIT_WINDOW = 60  # seconds
_last_sweep = 0.0

def _sweep_rate_limits(now: float) -> None:
    """Evict idle clients so _rate_limits cannot grow without bound.

    Without this, every distinct client IP leaves a permanent dict entry:
    its timestamp list is filtered down to empty but the key is never
    removed, so memory grows with the number of IPs ever seen. An entry
    whose timestamps are all older than the window can never block a
    future request, so it is safe to drop. Runs at most once per window
    to keep the common path cheap.
    """
    global _last_sweep
    if now - _last_sweep < RATE_LIMIT_WINDOW:
        return
    _last_sweep = now
    stale = [ip for ip, hits in _rate_limits.items()
             if all(now - t >= RATE_LIMIT_WINDOW for t in hits)]
    for ip in stale:
        del _rate_limits[ip]

def check_rate_limit(client_ip: str) -> bool:
    now = time.time()
    _sweep_rate_limits(now)
    recent = [t for t in _rate_limits[client_ip] if now - t < RATE_LIMIT_WINDOW]
    if len(recent) >= RATE_LIMIT_REQUESTS:
        _rate_limits[client_ip] = recent
        return False
    recent.append(now)
    _rate_limits[client_ip] = recent
    return True

# Redact sensitive values from exception messages before returning in HTTP responses.
# Strips Bearer tokens, known secret-like patterns, and any live env var values
# that look like credentials (length > 8, not a common word).
_SECRET_PATTERNS = [
    re.compile(r'Bearer\s+[A-Za-z0-9\-_\.]+', re.IGNORECASE),  # Authorization headers
    re.compile(r'[Aa][Pp][Ii][_-]?[Kk][Ee][Yy]["\s:=]+[\w\-\.]+'),  # api_key = ...
    re.compile(r'sk-[A-Za-z0-9]{20,}'),       # OpenAI-style keys
    re.compile(r'ghp_[A-Za-z0-9]{36}'),        # GitHub PATs
    re.compile(r'xox[baprs]-[0-9a-zA-Z\-]+'), # Slack tokens
    re.compile(r'AKIA[0-9A-Z]{16}'),           # AWS access keys
]

def _sanitize_error(exc: Exception) -> str:
    """Strip credential-like content from exception messages before HTTP response."""
    msg = str(exc)
    for pattern in _SECRET_PATTERNS:
        msg = pattern.sub('[REDACTED]', msg)
    # Also redact any live env var that looks like a credential (length > 8)
    for env_key in ("GROK_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY", "SSC_TOKEN"):
        val = os.environ.get(env_key, "")
        if val and len(val) > 8:
            msg = msg.replace(val, '[REDACTED]')
    return msg

# =============================================================================
# App Init
# =============================================================================

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

app = FastAPI(
    title="PsyClaw RAG Gateway",
    description="Offline-first, RAG-first, MCP-exposed stack",
    version="1.3.0"
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=FileResponse)
def serve_terminal_console():
    """Primary browser entry point — the Soul Console."""
    return FileResponse("static/terminal.html")

_origins = cfg.get("security", {}).get("allowed_origins", [])
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
)

try:
    retriever = HybridRetriever()
except IndexNotFoundError as e:
    import sys
    print(f"FATAL: {e.message}", file=sys.stderr)
    print("Run: python -m retrieval.indexer", file=sys.stderr)
    retriever = None

local_llm = LocalLLMClient()

grok = None
if cfg["app"]["mode"] == "hybrid" and cfg["models"]["grok"].get("enabled", False):
    grok = GrokClient()

personality = None
if cfg.get("personality", {}).get("enabled", False):
    personality = PersonalityManager(cfg)

compiled_graph = None
if retriever is not None:
    compiled_graph = build_graph(retriever, local_llm, grok, cfg, personality)

@app.post("/query", response_model=QueryResponse)
async def query_endpoint(request: Request, req: QueryRequest):
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip):
        audit_log({"event": "rate_limit_exceeded", "ip": client_ip})
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded (60/min)", "code": "RATE_LIMIT"}
        )

    if compiled_graph is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "Index not built. Run: python -m retrieval.indexer",
                    "code": "INDEX_NOT_FOUND"}
        )

    try:
        check_input(req.query)
    except PromptInjectionError as e:
        audit_log({"event": "prompt_injection_blocked", "query": req.query[:50]})
        raise HTTPException(
            status_code=400,
            detail={"error": e.message, "code": e.code, "details": e.details}
        )

    initial_state: GraphState = {
        "query": req.query,
        "user_confirmed_online": req.user_confirmed_online
    }

    try:
        result = compiled_graph.invoke(initial_state)
    except Exception as e:
        safe_msg = _sanitize_error(e)
        audit_log({"event": "graph_error", "query": req.query[:50], "error": safe_msg})
        raise HTTPException(status_code=500, detail={"error": safe_msg, "code": "GRAPH_ERROR"})

    needs_confirm = result.get("needs_user_confirm", False)
    answer_model = result.get("answer_model", "")

    if needs_confirm and not answer_model:
        top_score = result.get("top_score", 0.0)
        threshold = cfg["retrieval"]["min_score"]
        return QueryResponse(
            answer="",
            sources=[],
            retrieval_mode=result.get("retrieval_mode", "hybrid"),
            hit_count=len(result.get("retrieved_docs", [])),
            model_used="",
            needs_confirm=True,
            confirm_message=(
                f"Vault miss (best score: {top_score:.3f} < {threshold}). "
                f"Send query to Grok online? Re-submit with user_confirmed_online=true/false."
            )
        )

    docs = result.get("answer_sources", [])
    sources = []
    for d in docs:
        if isinstance(d, dict):
            sources.append(SourceInfo(
                source=d.get("source", ""),
                score=d.get("score", 0.0),
                chunk_id=d.get("chunk_id", -1),
                stem_tags=d.get("stem_tags", []),
                semantic_score=d.get("semantic_score"),
                semantic_rank=d.get("semantic_rank"),
                keyword_score=d.get("keyword_score"),
                keyword_rank=d.get("keyword_rank"),
                rrf_score=d.get("rrf_score"),
                rrf_semantic_contrib=d.get("rrf_semantic_contrib"),
                rrf_keyword_contrib=d.get("rrf_keyword_contrib")
            ))

    return QueryResponse(
        answer=result.get("answer", "[No answer generated]"),
        sources=sources,
        retrieval_mode=result.get("retrieval_mode", "hybrid"),
        hit_count=len(result.get("retrieved_docs", [])),
        model_used=result.get("answer_model", "unknown"),
        needs_confirm=False,
        error=result.get("error")
    )

@app.get("/soul")
def get_soul():
    if personality is None:
        raise HTTPException(status_code=404, detail="Personality system not enabled")
    return {
        "soul": personality.get_system_prompt_additive(),
        "version": personality.get_version(),
        "source": str(personality.soul_path)
    }

@app.post("/soul/propose")
def propose_soul_evolution(req: SoulEvolutionRequest):
    if personality is None:
        raise HTTPException(status_code=404, detail="Personality system not enabled")
    proposal = personality.propose_evolution(req.new_soul, req.reason)
    audit_log({"event": "soul_evolution_proposed", "reason": req.reason})
    return proposal

@app.post("/soul/apply")
def apply_soul_evolution(req: SoulEvolutionRequest):
    if personality is None:
        raise HTTPException(status_code=404, detail="Personality system not enabled")
    result = personality.apply_evolution(req.new_soul, req.reason)
    audit_log({"event": "soul_evolution_applied", "reason": req.reason})
    return result

@app.post("/soul/reload")
def reload_soul():
    if personality is None:
        raise HTTPException(status_code=404, detail="Personality system not enabled")
    personality.reload()
    return {"status": "reloaded", "version": personality.get_version()}

@app.get("/health", response_model=HealthResponse)
def health():
    statuses = check_all()
    return HealthResponse(
        status="ok" if all(s.healthy for s in statuses) else "degraded",
        services={s.name: {"healthy": s.healthy, "latency_ms": s.latency_ms, "error": s.error} for s in statuses},
        index_ready=retriever is not None,
        graph_ready=compiled_graph is not None
    )
