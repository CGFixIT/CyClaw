"""LM Studio (local) and Grok (online fallback) client wrappers.

Both clients use the OpenAI-compatible /chat/completions endpoint.
Grok is only instantiated in hybrid mode when explicitly enabled.

Transient failures (timeouts, transport/network errors, and retryable HTTP
statuses — 5xx and 429) are retried with bounded exponential backoff. Client
errors (other 4xx) and unexpected exceptions fail fast — retrying a 400/401
only wastes time and, for Grok, external credits. Retry is config-driven via a
``retry`` block under each model; when absent, ``max_retries`` defaults to 0,
preserving the original single-attempt behavior.
"""

import json
import os
import time
from typing import Callable, Optional

import httpx
import yaml

from utils.errors import GrokServiceError, LLMServiceError, RAGError

_RETRYABLE_STATUS_FLOOR = 500
_RETRYABLE_EXTRA_STATUS = frozenset({429})


def _is_retryable_status(status: int) -> bool:
    """5xx server errors and 429 (rate limit) are transient; other 4xx are not."""
    return status >= _RETRYABLE_STATUS_FLOOR or status in _RETRYABLE_EXTRA_STATUS


def _extract_content(resp: httpx.Response) -> str:
    """Pull ``choices[0].message.content`` from a 200 response, failing clearly.

    A 2xx body that is not valid JSON or lacks the expected OpenAI-compatible
    shape (e.g. an upstream proxy returning an HTML error page, or an
    ``{"error": ...}`` payload) would otherwise surface as a bare ``KeyError``/
    ``JSONDecodeError`` with a cryptic message. Raising a descriptive
    ``ValueError`` here lets the caller's ``on_other`` map it to the project's
    typed error with an auditable message. The shape is deterministic, so this
    is not retried — a retry would re-fetch the same malformed body."""
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        raise ValueError(f"malformed LLM response ({type(e).__name__}): {e}") from e


def _read_retry(model_cfg: dict) -> tuple[int, float]:
    """Parse the optional ``retry`` block; default to no retries (backward compatible)."""
    retry_cfg = model_cfg.get("retry") or {}
    max_retries = int(retry_cfg.get("max_retries", 0))
    backoff_base = float(retry_cfg.get("backoff_base_sec", 1.0))
    return max_retries, backoff_base


def _post_with_retry(
    *,
    do_post: Callable[[], httpx.Response],
    max_retries: int,
    backoff_base: float,
    on_http: Callable[[httpx.HTTPStatusError], RAGError],
    on_timeout: Callable[[httpx.TimeoutException], RAGError],
    on_other: Callable[[Exception], RAGError],
) -> str:
    """POST with bounded exponential-backoff retry on transient failures.

    Retries timeouts, transport/network errors, and retryable HTTP statuses
    (5xx, 429) up to ``max_retries`` extra attempts, sleeping
    ``backoff_base * 2**attempt`` seconds between tries. Other 4xx statuses and
    any non-transport exception fail fast. ``max_retries == 0`` reproduces the
    original single-attempt behavior. The ``on_*`` callables map the terminal
    failure to the caller's typed error so messages/codes stay unchanged.
    """
    for attempt in range(max_retries + 1):
        try:
            resp = do_post()
            resp.raise_for_status()
            return _extract_content(resp)
        except httpx.HTTPStatusError as e:
            if attempt < max_retries and _is_retryable_status(e.response.status_code):
                time.sleep(backoff_base * (2 ** attempt))
                continue
            raise on_http(e) from e
        except httpx.TimeoutException as e:
            if attempt < max_retries:
                time.sleep(backoff_base * (2 ** attempt))
                continue
            raise on_timeout(e) from e
        except httpx.TransportError as e:
            # Connection/read/write/protocol errors below the HTTP layer.
            if attempt < max_retries:
                time.sleep(backoff_base * (2 ** attempt))
                continue
            raise on_other(e) from e
        except Exception as e:
            raise on_other(e) from e
    raise AssertionError("unreachable: retry loop exited without return/raise")  # pragma: no cover


class LocalLLMClient:
    def __init__(self, config_path: str = "config.yaml", cfg: Optional[dict] = None):
        if cfg is None:
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
        llm_cfg = cfg["models"]["local_llm"]
        self.base_url = llm_cfg["base_url"]
        self.model = llm_cfg["model"]
        self.max_tokens = llm_cfg["max_tokens"]
        self.temperature = llm_cfg["temperature"]
        self.timeout = llm_cfg["timeout_sec"]
        self.retry_max, self.retry_backoff = _read_retry(llm_cfg)
        self._client = httpx.Client(timeout=self.timeout)

    def close(self) -> None:
        self._client.close()

    def generate(self, prompt: str) -> str:
        def do_post() -> httpx.Response:
            return self._client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature
                },
            )

        return _post_with_retry(
            do_post=do_post,
            max_retries=self.retry_max,
            backoff_base=self.retry_backoff,
            on_http=lambda e: LLMServiceError(
                f"LM Studio HTTP error: {e.response.status_code}",
                details={"status": e.response.status_code},
            ),
            on_timeout=lambda e: LLMServiceError(
                "LM Studio timeout", details={"timeout_sec": self.timeout}
            ),
            on_other=lambda e: LLMServiceError(f"LM Studio error: {str(e)}"),
        )

class GrokClient:
    def __init__(self, config_path: str = "config.yaml", cfg: Optional[dict] = None):
        if cfg is None:
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
        grok_cfg = cfg["models"]["grok"]
        self.base_url = grok_cfg["base_url"]
        self.model = grok_cfg["model"]
        self.max_tokens = grok_cfg["max_tokens"]
        self.temperature = grok_cfg["temperature"]
        self.timeout = grok_cfg["timeout_sec"]
        self.retry_max, self.retry_backoff = _read_retry(grok_cfg)
        self.api_key = os.environ.get("GROK_API_KEY", "")
        self._client = httpx.Client(timeout=self.timeout)

    def close(self) -> None:
        self._client.close()

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise GrokServiceError("GROK_API_KEY not set",
                                    details={"required_env": "GROK_API_KEY"})

        def do_post() -> httpx.Response:
            return self._client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature
                },
            )

        return _post_with_retry(
            do_post=do_post,
            max_retries=self.retry_max,
            backoff_base=self.retry_backoff,
            on_http=lambda e: GrokServiceError(
                f"Grok HTTP {e.response.status_code}",
                details={"status": e.response.status_code},
            ),
            on_timeout=lambda e: GrokServiceError(
                "Grok timeout", details={"timeout_sec": self.timeout}
            ),
            on_other=lambda e: GrokServiceError(f"Grok error: {str(e)}"),
        )
