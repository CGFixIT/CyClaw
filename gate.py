#!/usr/bin/env python

"""CyClaw FastAPI Gateway — HTTP/MCP entry point.

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
import asyncio
import hmac
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
    # Compare against the expected kill value, not a generic "non-empty" check.
    # CHROMA_OTEL_* are intentionally set to "" to disable them; the old
    # `v not in ("", "NOT SET")` check marked them MISSING on every startup.
    status = "OK" if v == _TELEMETRY_KILL[k] else "MISSING"
    print(f"  {status}  {k}={v}")

import logging
import yaml
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from graph import build_graph, GraphState
from retrieval.hybrid_search import HybridRetriever
from llm.client import LocalLLMClient, GrokClient
from schemas.api import QueryRequest, QueryResponse, SourceInfo, HealthResponse, SoulEvolutionRequest
from utils.logger import audit_log, setup_logging
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from utils.sanitizer import check_input
from utils.errors import (
    RAGError, PromptInjectionError, IndexNotFoundError, LLMServiceError
)
from utils.health import check_all
from utils.personality import PersonalityManager

_bearer_scheme = HTTPBearer(auto_error=False)

def require_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
):
    # Fail-closed (PR #99 #4). Previously, when CYCLAW_API_KEY was unset the
    # server ran in "open mode" and require_api_key was a no-op, leaving every
    # /soul/* mutation endpoint unauthenticated. Now, if no key is configured the
    # endpoint is REFUSED rather than left open — no key is generated, logged, or
    # stored. Set CYCLAW_API_KEY to enable soul mutations.
    api_key = os.environ.get("CYCLAW_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=401,
                            detail="Soul mutation disabled: CYCLAW_API_KEY not set")
    # Constant-time comparison: a plain `!=` short-circuits on the first
    # differing byte, leaking key length/prefix via response timing. compare_digest
    # runs in time independent of how many leading characters match.
    if not credentials or not hmac.compare_digest(credentials.credentials, api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

# Simple in-memory rate limiter (per-IP for /query). The limiter itself lives
# in utils/ratelimit.py as a lock-synchronized class so the gateway and its
# tests share one implementation (no duplicated logic) and concurrent requests
# under FastAPI's threadpool cannot interleave and overcount.
from fastapi import Request
from utils.ratelimit import RateLimiter

RATE_LIMIT_REQUESTS = 60
RATE_LIMIT_WINDOW = 60  # seconds
_rate_limiter = RateLimiter(max_requests=RATE_LIMIT_REQUESTS, window_seconds=RATE_LIMIT_WINDOW)

def check_rate_limit(client_ip: str) -> bool:
    """Thin gateway-level wrapper over the shared RateLimiter instance."""
    return _rate_limiter.allow(client_ip)

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
    # Also redact any live env var that looks like a credential (length > 8).
    # CYCLAW_API_KEY is the server's own auth secret — if it ever surfaced in an
    # auth-library or middleware traceback it must not be echoed in a 500 body.
    for env_key in ("GROK_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY", "SSC_TOKEN", "CYCLAW_API_KEY"):
        val = os.environ.get(env_key, "")
        if val and len(val) > 8:
            msg = msg.replace(val, '[REDACTED]')
    return msg

# =============================================================================
# App Init
# =============================================================================

with open("config.yaml", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

setup_logging(cfg)
logger = logging.getLogger("cyclaw.gate")

if not os.environ.get("CYCLAW_API_KEY", ""):
    logger.warning(
        "CYCLAW_API_KEY is not set — soul-mutation endpoints (/soul/*) are DISABLED "
        "(fail-closed). Set CYCLAW_API_KEY to enable them."
    )

app = FastAPI(
    title="CyClaw RAG Gateway",
    description="Offline-first, RAG-first, MCP-exposed stack",
    version="1.4.0"
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
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=False,
)

# TrustedHostMiddleware (PR #99 #3): reject requests whose Host header is not in
# the allow-list. CORS governs response *readability*; it does not stop a
# DNS-rebinding page from executing state-changing POST /soul/* server-side. The
# Host check does. Added after CORS so it is the OUTERMOST middleware (runs first
# on each request). Host matching ignores port; the list is config-driven so an
# operator can add any name/IP they reach CyClaw by (e.g. the home-lab LAN IP).
from starlette.middleware.trustedhost import TrustedHostMiddleware
_allowed_hosts = cfg.get("security", {}).get("allowed_hosts", ["127.0.0.1", "localhost"])  # DevSkim: ignore DS162092,DS137138 - loopback host allow-list by design
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)

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
    compiled_graph = build_graph(
        retriever=retriever, llm=local_llm, grok=grok, cfg=cfg, personality=personality
    )

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
        # Pass the full query: audit_log() SHA-256-hashes the "query" field, so
        # truncating here yields a hash of only the first 50 chars that diverges
        # from the canonical full-query hash written by the graph audit node and
        # the MCP path. No raw text is persisted either way.
        audit_log({"event": "prompt_injection_blocked", "query": req.query})
        raise HTTPException(
            status_code=400,
            detail={"error": e.message, "code": e.code, "details": e.details}
        )

    initial_state: GraphState = {
        "query": req.query,
        "user_confirmed_online": req.user_confirmed_online
    }

    try:
        result = await asyncio.to_thread(compiled_graph.invoke, initial_state)
    except Exception as e:
        safe_msg = _sanitize_error(e)
        audit_log({"event": "graph_error", "query": req.query, "error": safe_msg})
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
async def get_soul():
    if personality is None:
        raise HTTPException(status_code=404, detail="Personality system not enabled")
    return {
        "soul": personality.get_system_prompt_additive(),
        "version": personality.get_version(),
        "source": str(personality.soul_path)
    }

@app.post("/soul/propose", dependencies=[Depends(require_api_key)])
async def propose_soul_evolution(req: SoulEvolutionRequest):
    if personality is None:
        raise HTTPException(status_code=404, detail="Personality system not enabled")
    proposal = await asyncio.to_thread(personality.propose_evolution, req.new_soul, req.reason)
    audit_log({"event": "soul_evolution_proposed", "reason": req.reason})
    return proposal

@app.post("/soul/apply", dependencies=[Depends(require_api_key)])
async def apply_soul_evolution(req: SoulEvolutionRequest):
    if personality is None:
        raise HTTPException(status_code=404, detail="Personality system not enabled")
    try:
        result = await asyncio.to_thread(personality.apply_evolution, req.new_soul, req.reason)
    except PromptInjectionError as e:
        audit_log({"event": "soul_apply_injection_blocked", "reason": req.reason})
        raise HTTPException(
            status_code=400,
            detail={"error": e.message, "code": e.code, "details": e.details},
        )
    return result

@app.post("/soul/reload", dependencies=[Depends(require_api_key)])
async def reload_soul():
    if personality is None:
        raise HTTPException(status_code=404, detail="Personality system not enabled")
    await asyncio.to_thread(personality.reload)
    return {"status": "reloaded", "version": personality.get_version()}

@app.post("/soul/restore", dependencies=[Depends(require_api_key)])
async def restore_soul():
    if personality is None:
        raise HTTPException(status_code=404, detail="Personality system not enabled")
    try:
        result = await asyncio.to_thread(personality.restore_from_backup)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/health", response_model=HealthResponse)
async def health():
    statuses = await asyncio.to_thread(check_all)
    return HealthResponse(
        status="ok" if all(s.healthy for s in statuses) else "degraded",
        services={s.name: {"healthy": s.healthy, "latency_ms": s.latency_ms, "error": s.error} for s in statuses},
        index_ready=retriever is not None,
        graph_ready=compiled_graph is not None
    )


def main() -> None:
    """Console entry point for ``cyclaw-server`` (see pyproject [project.scripts]).

    Serves the FastAPI app on the loopback host/port from config.yaml. Without
    this, the declared ``cyclaw-server = "gate:main"`` script raised
    AttributeError because no ``main`` symbol existed in this module.
    """
    import uvicorn

    api_cfg = cfg.get("api", {})
    uvicorn.run(
        app,
        host=api_cfg.get("host", "127.0.0.1"),  # DevSkim: ignore DS162092 - loopback-only binding by design
        port=api_cfg.get("port", 8787),
    )


if __name__ == "__main__":
    main()
