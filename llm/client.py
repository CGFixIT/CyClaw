"""LM Studio (local) and Grok (online fallback) client wrappers.

Both clients use the OpenAI-compatible /chat/completions endpoint.
Grok is only instantiated in hybrid mode when explicitly enabled.
"""

import os
from typing import Optional

import httpx
import yaml

from utils.errors import GrokServiceError, LLMServiceError


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
        self._client = httpx.Client(timeout=self.timeout)

    def close(self) -> None:
        self._client.close()

    def generate(self, prompt: str) -> str:
        try:
            resp = self._client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise LLMServiceError(f"LM Studio HTTP error: {e.response.status_code}",
                                   details={"status": e.response.status_code}) from e
        except httpx.TimeoutException as e:
            raise LLMServiceError("LM Studio timeout", details={"timeout_sec": self.timeout}) from e
        except Exception as e:
            raise LLMServiceError(f"LM Studio error: {str(e)}") from e

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
        try:
            resp = self._client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise GrokServiceError(f"Grok HTTP {e.response.status_code}",
                                    details={"status": e.response.status_code}) from e
        except httpx.TimeoutException as e:
            raise GrokServiceError("Grok timeout", details={"timeout_sec": self.timeout}) from e
        except Exception as e:
            raise GrokServiceError(f"Grok error: {str(e)}") from e
