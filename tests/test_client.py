"""Unit tests for llm/client.py — LocalLLMClient + GrokClient.

These exercise the error-mapping contract that the graph nodes rely on
(``local_llm_node`` / ``grok_fallback_node`` only ``except LLMServiceError`` /
``GrokServiceError``). Every wire-level failure mode — HTTP status, timeout,
unexpected exception — must be translated into the project's typed errors with
the right ``code`` and ``details``; a leaked ``httpx`` exception would escape the
node handlers and surface as a raw 500.

No live LM Studio / xAI endpoint is contacted: the per-instance ``httpx.Client``
is monkeypatched. Real ``httpx.Request``/``Response`` objects are used so the
``e.response.status_code`` path in the production code runs unmocked.
"""

import httpx
import pytest
import yaml

from llm.client import LocalLLMClient, GrokClient
from utils.errors import LLMServiceError, GrokServiceError

_URL = "http://127.0.0.1:1234/v1/chat/completions"  # DevSkim: ignore DS162092,DS137138 - loopback test URL


def _write_config(tmp_path) -> str:
    """Minimal config.yaml with the models.* blocks both clients read."""
    cfg = {
        "models": {
            "local_llm": {
                "base_url": "http://127.0.0.1:1234/v1",  # DevSkim: ignore DS162092,DS137138
                "model": "test-model",
                "max_tokens": 256,
                "temperature": 0.1,
                "timeout_sec": 5,
            },
            "grok": {
                "base_url": "https://api.x.ai/v1",
                "model": "grok-4",
                "max_tokens": 256,
                "temperature": 0.2,
                "timeout_sec": 5,
            },
        }
    }
    p = tmp_path / "config.yaml"
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f)
    return str(p)


class _FakePost:
    """Replacement for ``httpx.Client.post`` with a scripted outcome."""

    def __init__(self, *, response: httpx.Response = None, raises: Exception = None):
        self._response = response
        self._raises = raises
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self._raises is not None:
            raise self._raises
        return self._response


def _ok_response(content: str = "hello from llm") -> httpx.Response:
    req = httpx.Request("POST", _URL)
    return httpx.Response(
        200, json={"choices": [{"message": {"content": content}}]}, request=req
    )


def _status_response(status: int) -> httpx.Response:
    req = httpx.Request("POST", _URL)
    return httpx.Response(status, json={"error": "boom"}, request=req)


# =============================================================================
# LocalLLMClient
# =============================================================================

class TestLocalLLMClient:
    def test_init_reads_config(self, tmp_path):
        client = LocalLLMClient(_write_config(tmp_path))
        assert client.model == "test-model"
        assert client.max_tokens == 256
        assert client.timeout == 5
        client.close()

    def test_generate_success(self, tmp_path):
        client = LocalLLMClient(_write_config(tmp_path))
        fake = _FakePost(response=_ok_response("answer text"))
        client._client.post = fake
        assert client.generate("a prompt") == "answer text"
        # The request targets the /chat/completions endpoint with the model.
        url, kwargs = fake.calls[0]
        assert url.endswith("/chat/completions")
        assert kwargs["json"]["model"] == "test-model"
        assert kwargs["json"]["messages"][0]["content"] == "a prompt"
        client.close()

    def test_generate_http_error_maps_to_llm_service_error(self, tmp_path):
        client = LocalLLMClient(_write_config(tmp_path))
        client._client.post = _FakePost(response=_status_response(503))
        with pytest.raises(LLMServiceError) as exc:
            client.generate("a prompt")
        assert exc.value.code == "LLM_SERVICE_ERROR"
        assert exc.value.details.get("status") == 503
        client.close()

    def test_generate_timeout_maps_to_llm_service_error(self, tmp_path):
        client = LocalLLMClient(_write_config(tmp_path))
        client._client.post = _FakePost(raises=httpx.TimeoutException("timed out"))
        with pytest.raises(LLMServiceError) as exc:
            client.generate("a prompt")
        assert exc.value.details.get("timeout_sec") == 5
        client.close()

    def test_generate_unexpected_error_maps_to_llm_service_error(self, tmp_path):
        client = LocalLLMClient(_write_config(tmp_path))
        client._client.post = _FakePost(raises=ValueError("connection reset"))
        with pytest.raises(LLMServiceError) as exc:
            client.generate("a prompt")
        assert "connection reset" in exc.value.message
        client.close()


# =============================================================================
# GrokClient
# =============================================================================

class TestGrokClient:
    def test_is_available_reflects_api_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GROK_API_KEY", "xai-secret")
        client = GrokClient(_write_config(tmp_path))
        assert client.is_available() is True
        client.close()

        monkeypatch.delenv("GROK_API_KEY", raising=False)
        client2 = GrokClient(_write_config(tmp_path))
        assert client2.is_available() is False
        client2.close()

    def test_generate_without_key_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GROK_API_KEY", raising=False)
        client = GrokClient(_write_config(tmp_path))
        with pytest.raises(GrokServiceError) as exc:
            client.generate("a prompt")
        assert exc.value.details.get("required_env") == "GROK_API_KEY"
        client.close()

    def test_generate_success_sends_bearer(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GROK_API_KEY", "xai-secret")
        client = GrokClient(_write_config(tmp_path))
        fake = _FakePost(response=_ok_response("grok answer"))
        client._client.post = fake
        assert client.generate("a prompt") == "grok answer"
        _url, kwargs = fake.calls[0]
        assert kwargs["headers"]["Authorization"] == "Bearer xai-secret"
        client.close()

    def test_generate_http_error_maps_to_grok_service_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GROK_API_KEY", "xai-secret")
        client = GrokClient(_write_config(tmp_path))
        client._client.post = _FakePost(response=_status_response(429))
        with pytest.raises(GrokServiceError) as exc:
            client.generate("a prompt")
        assert exc.value.details.get("status") == 429
        client.close()

    def test_generate_timeout_maps_to_grok_service_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GROK_API_KEY", "xai-secret")
        client = GrokClient(_write_config(tmp_path))
        client._client.post = _FakePost(raises=httpx.TimeoutException("timed out"))
        with pytest.raises(GrokServiceError) as exc:
            client.generate("a prompt")
        assert exc.value.details.get("timeout_sec") == 5
        client.close()

    def test_generate_unexpected_error_maps_to_grok_service_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GROK_API_KEY", "xai-secret")
        client = GrokClient(_write_config(tmp_path))
        client._client.post = _FakePost(raises=ValueError("dns failure"))
        with pytest.raises(GrokServiceError) as exc:
            client.generate("a prompt")
        assert "dns failure" in exc.value.message
        client.close()
