"""Pydantic models for the PsyClaw FastAPI gateway.

Covers query request/response, source info, health, and soul evolution.
"""

from pydantic import BaseModel, Field
from typing import List, Optional

class QueryRequest(BaseModel):
    # min_length=1 rejects empty queries at the schema boundary (HTTP 422)
    # before any retrieval/LLM work is done.
    query: str = Field(min_length=1)
    user_confirmed_online: Optional[bool] = None

class SourceInfo(BaseModel):
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
    answer: str
    sources: List[SourceInfo]
    retrieval_mode: str
    hit_count: int
    model_used: str
    needs_confirm: bool = False
    confirm_message: Optional[str] = None
    error: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    services: dict
    index_ready: bool
    graph_ready: bool

class SoulEvolutionRequest(BaseModel):
    new_soul: str
    reason: str
