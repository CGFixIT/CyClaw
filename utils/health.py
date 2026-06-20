"""Health checks for external dependencies.

Only checks LM Studio (and optionally Grok). No Ollama —
embeddings are local sentence-transformers.
"""

import time
from functools import lru_cache
from typing import List

import httpx
import yaml

from .errors import HealthStatus, LLMServiceError

@lru_cache(maxsize=8)
def _health_cfg(config_path: str) -> dict:
    """Parse config once per path. check_all runs on every /health request, so
    re-reading and re-parsing the YAML each time was avoidable disk + parse I/O.
    """
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def check_all(config_path: str = "config.yaml") -> List[HealthStatus]:
    cfg = _health_cfg(config_path)
    results = []
    llm_base = cfg["models"]["local_llm"]["base_url"]
    results.append(_ping(f"{llm_base}/models", "lm_studio"))
    if (cfg["app"]["mode"] == "hybrid" and
            cfg["models"]["grok"].get("enabled", False)):
        grok_base = cfg["models"]["grok"]["base_url"]
        results.append(_ping(f"{grok_base}/models", "grok_api"))
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

def _ping(url: str, name: str) -> HealthStatus:
    try:
        start = time.monotonic()
        resp = httpx.get(url, timeout=5.0)
        latency = (time.monotonic() - start) * 1000
        resp.raise_for_status()
        return HealthStatus(name=name, healthy=True, latency_ms=round(latency, 1))
    except Exception as e:
        return HealthStatus(name=name, healthy=False, error=str(e))
