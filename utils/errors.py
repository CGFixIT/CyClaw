"""Structured error types for the CyClaw RAG pipeline.

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

class SyncError(RAGError):
    """Base error for out-of-band Dropbox corpus sync operations."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, code="SYNC_ERROR", details=details)


class RcloneNotInstalledError(SyncError):
    """rclone binary not found on PATH."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, details=details)
        self.code = "RCLONE_NOT_INSTALLED"


class RcloneVersionError(SyncError):
    """rclone is installed but the version is below the required floor."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, details=details)
        self.code = "RCLONE_VERSION_TOO_OLD"


class SyncConfigError(SyncError):
    """The sync: block in config.yaml is missing or invalid."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, details=details)
        self.code = "SYNC_CONFIG_INVALID"


class SchedulerError(SyncError):
    """Cron / systemd / launchd / Task Scheduler registration or removal failed."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, details=details)
        self.code = "SYNC_SCHEDULER_ERROR"


class SyncRuntimeError(SyncError):
    """rclone subprocess failed at runtime (non-zero exit, safety-fuse abort, etc.)."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, details=details)
        self.code = "SYNC_RUNTIME_ERROR"


@dataclass
class HealthStatus:
    name: str
    healthy: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
