"""Health checks for external dependencies.

Only checks LM Studio (and optionally Grok). No Ollama —
embeddings are local sentence-transformers.
"""

import os
import re
import time

import httpx
import yaml

from .errors import HealthStatus, LLMServiceError

_cfg_cache: dict[str, tuple[dict, float]] = {}
_cfg_ttl_sec = 60


def _health_cfg(config_path: str) -> dict:
    """Parse config with 60-second TTL to balance performance and hot-reload responsiveness.

    If config.yaml is edited post-startup, the cache expires within 60 seconds,
    allowing operators to toggle settings (e.g. Grok) without restarting.
    """
    now = time.monotonic()
    if config_path in _cfg_cache:
        cached_cfg, cached_at = _cfg_cache[config_path]
        if now - cached_at < _cfg_ttl_sec:
            return cached_cfg
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    _cfg_cache[config_path] = (cfg, now)
    return cfg

def check_all(config_path: str = "config.yaml") -> list[HealthStatus]:
    cfg = _health_cfg(config_path)
    results = []
    llm_base = cfg["models"]["local_llm"]["base_url"]
    results.append(_ping(f"{llm_base}/models", "lm_studio"))
    if (cfg["app"]["mode"] == "hybrid" and
            cfg["models"]["grok"].get("enabled", False)):
        grok_base = cfg["models"]["grok"]["base_url"]
        # xAI's /v1/models is an authenticated endpoint: without a Bearer token it
        # returns 401, which made grok_api report *unhealthy* on every probe even
        # when the API was fully up — masking real outages. Send the same key the
        # GrokClient uses. With no key configured (the default offline posture),
        # report a clear "key not set" state instead of a misleading 401/network
        # error, and skip the doomed request entirely.
        api_key = os.environ.get("GROK_API_KEY", "")
        if api_key:
            results.append(_ping(
                f"{grok_base}/models", "grok_api",
                headers={"Authorization": f"Bearer {api_key}"},
            ))
        else:
            results.append(HealthStatus(
                name="grok_api", healthy=False,
                error="GROK_API_KEY not set (hybrid mode enabled but no API key)",
            ))
    results.append(HealthStatus(name="embeddings_local", healthy=True, latency_ms=0.0))
    return results

def require_healthy(config_path: str = "config.yaml") -> None:
    statuses = check_all(config_path)
    for s in statuses:
        if not s.healthy and s.name == "lm_studio":
            raise LLMServiceError(
                f"{s.name} unreachable: {s.error}",
                details={"endpoint": s.name}
            )

def _ping(url: str, name: str, headers: dict | None = None) -> HealthStatus:
    try:
        start = time.monotonic()
        resp = httpx.get(url, timeout=5.0, headers=headers or {})
        latency = (time.monotonic() - start) * 1000
        resp.raise_for_status()
        return HealthStatus(name=name, healthy=True, latency_ms=round(latency, 1))
    except Exception as e:
        # Redact the URL (which may contain credentials or internal hostnames)
        # from the exception message before surfacing it in the public /health response.
        safe_error = re.sub(r'https?://\S+', '[URL REDACTED]', str(e))
        return HealthStatus(name=name, healthy=False, error=safe_error)
