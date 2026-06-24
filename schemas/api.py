"""Pydantic models for the CyClaw FastAPI gateway.

Covers query request/response, source info, health, and soul evolution.

Hardened in feature/CyClaw-Agent: strict=True + extra='forbid' on all models
(prevents silent data injection or unexpected fields in agentic flows).
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    # min_length=1 rejects empty queries at the schema boundary (HTTP 422)
    # before any retrieval/LLM work is done.
    query: str = Field(min_length=1)
    user_confirmed_online: Optional[bool] = None

class SourceInfo(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    source: str
    score: float
    chunk_id: int
    stem_tags: List[str] = []
    semantic_score: Optional[float] = None
    semantic_rank: Optional[int] = None
    keyword_score: Optional[float] = None
    keyword_rank: Optional[int] = None
    rrf_score: Optional[float] = None
    rrf_semantic_contrib: Optional[float] = None
    rrf_keyword_contrib: Optional[float] = None

class QueryResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    answer: str
    sources: List[SourceInfo]
    retrieval_mode: str
    hit_count: int
    model_used: str
    needs_confirm: bool = False
    confirm_message: Optional[str] = None
    error: Optional[str] = None

class HealthResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    status: str
    services: dict
    index_ready: bool
    graph_ready: bool

class SoulEvolutionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    new_soul: str = Field(min_length=1, max_length=65536)
    reason: str = Field(min_length=1)


# --- Ops console request models -------------------------------------------------
# These back the terminal console's Sync + Agentic panels (/ops/sync, /ops/agentic).
# action is a closed Literal so an unknown verb is rejected at the schema boundary
# (HTTP 422) before any subprocess is spawned; extra='forbid' + strict=True block
# silent field injection. The gateway never imports sync/ or agentic/ — it shells
# out via utils.ops_runner — so these models are the only typed contract crossing
# the out-of-band boundary.
class OpsSyncRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal["status", "test", "sync", "schedule", "unschedule"]
    dry_run: bool = False


class OpsAgenticRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal["status", "test", "context", "propose-skill", "apply-skill"]
    # context selectors
    pr: Optional[int] = Field(default=None, ge=1)
    issue: Optional[int] = Field(default=None, ge=1)
    no_diff: bool = False
    # skills-registry fields (propose-skill / apply-skill)
    name: Optional[str] = Field(default=None, max_length=128)
    desc: Optional[str] = Field(default=None, max_length=512)
    body: Optional[str] = Field(default=None, max_length=65536)
    reason: Optional[str] = Field(default=None, max_length=4096)
    confirm: bool = False
