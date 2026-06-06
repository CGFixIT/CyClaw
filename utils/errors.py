"""Structured error types for the PsyClaw RAG pipeline.

Typed exceptions with code + details fields that the gateway
catches and maps to proper HTTP responses.
"""

from dataclasses import dataclass
from typing import Optional

class RAGError(Exception):
    def __init__(self, message: str, code: str = "RAG_ERROR", details: Optional[dict] = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)

class EmbeddingServiceError(RAGError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, code="EMBEDDING_ERROR", details=details)

class LLMServiceError(RAGError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, code="LLM_SERVICE_ERROR", details=details)

class GrokServiceError(RAGError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, code="GROK_SERVICE_ERROR", details=details)

class IndexNotFoundError(RAGError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, code="INDEX_NOT_FOUND", details=details)

class CorpusEmptyError(RAGError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, code="CORPUS_EMPTY", details=details)

class PromptInjectionError(RAGError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, code="PROMPT_INJECTION_BLOCKED", details=details)

class ConfigError(RAGError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, code="CONFIG_ERROR", details=details)

@dataclass
class HealthStatus:
    name: str
    healthy: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
