"""Unit tests for utils/health.py — external-dependency health probes.

health.py was previously only ever *mocked out* (``patch("gate.check_all")``
in test_gate.py); none of its own branches were exercised directly:
  - ``_ping`` success vs. failure (and the URL-redaction on failure)
  - ``check_all`` offline (LM Studio only) vs. hybrid (Grok) paths
  - the hybrid Grok key-set / key-missing split
  - ``require_healthy`` raising when LM Studio is down
  - the ``_health_cfg`` per-path parse cache

All HTTP is mocked; no live service is required.
"""

import httpx
import pytest
import yaml

from utils import health
from utils.errors import LLMServiceError

# Inert test fixtures mirroring the real loopback LM Studio endpoint
# (http://127.0.0.1:1234, the value shipped in config.yaml) so the probes are
# exercised against realistic inputs. No socket is ever opened -- httpx is
# mocked in every test. DevSkim flags the http scheme + localhost on URL
# literals; suppressed here per the repo convention (cf. the inline
# `# DevSkim: ignore` markers in retrieval/hybrid_search.py and
# utils/personality.py).
_LM_BASE = "http://127.0.0.1:1234/v1"  # DevSkim: ignore DS137138,DS162092
_LM_MODELS = "http://127.0.0.1:1234/models"  # DevSkim: ignore DS137138,DS162092
_HOST_MODELS = "http://host/models"  # DevSkim: ignore DS137138


def _write_cfg(tmp_path, *, mode="offline", grok_enabled=False):
    cfg = {
        "app": {"mode": mode},
        "models": {
            "local_llm": {"base_url": _LM_BASE},
            "grok": {"enabled": grok_enabled, "base_url": "https://api.x.ai/v1"},
        },
    }
    p = tmp_path / "config.yaml"
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f)
    return str(p)


class _OKResp:
    def raise_for_status(self):
        return None


@pytest.fixture(autouse=True)
def _clear_health_cfg_cache():
    # _health_cfg is module-level lru_cache; isolate every test from cached parses.
    health._health_cfg.cache_clear()
    yield
    health._health_cfg.cache_clear()


class TestPing:
    def test_ping_healthy(self, monkeypatch):
        monkeypatch.setattr(health.httpx, "get", lambda url, **kw: _OKResp())
        status = health._ping(_HOST_MODELS, "lm_studio")
        assert status.healthy is True
        assert status.name == "lm_studio"
        assert status.latency_ms is not None
        assert status.error is None

    def test_ping_unreachable_redacts_url(self, monkeypatch):
        def boom(url, **kw):
            raise httpx.ConnectError(f"cannot connect to {_LM_MODELS}")

        monkeypatch.setattr(health.httpx, "get", boom)
        status = health._ping(_LM_MODELS, "lm_studio")
        assert status.healthy is False
        # The URL (possible creds / internal hostnames) must not leak into /health.
        assert "127.0.0.1" not in status.error
        assert "[URL REDACTED]" in status.error

    def test_ping_non_2xx_is_unhealthy(self, monkeypatch):
        request = httpx.Request("GET", _HOST_MODELS)
        response = httpx.Response(503, request=request)

        class _Resp:
            def raise_for_status(self):
                raise httpx.HTTPStatusError("503", request=request, response=response)

        monkeypatch.setattr(health.httpx, "get", lambda url, **kw: _Resp())
        status = health._ping(_HOST_MODELS, "lm_studio")
        assert status.healthy is False


class TestCheckAll:
    def test_offline_mode_pings_only_lm_studio(self, tmp_path, monkeypatch):
        cfg_path = _write_cfg(tmp_path, mode="offline")
        monkeypatch.setattr(health.httpx, "get", lambda url, **kw: _OKResp())
        statuses = health.check_all(cfg_path)
        names = {s.name for s in statuses}
        assert names == {"lm_studio", "embeddings_local"}
        assert all(s.healthy for s in statuses)

    def test_hybrid_without_key_reports_key_not_set(self, tmp_path, monkeypatch):
        cfg_path = _write_cfg(tmp_path, mode="hybrid", grok_enabled=True)
        monkeypatch.setattr(health.httpx, "get", lambda url, **kw: _OKResp())
        monkeypatch.delenv("GROK_API_KEY", raising=False)
        statuses = health.check_all(cfg_path)
        grok = next(s for s in statuses if s.name == "grok_api")
        assert grok.healthy is False
        assert "GROK_API_KEY not set" in grok.error

    def test_hybrid_with_key_pings_grok_with_bearer_auth(self, tmp_path, monkeypatch):
        cfg_path = _write_cfg(tmp_path, mode="hybrid", grok_enabled=True)
        seen = {}

        def fake_get(url, **kw):
            seen["url"] = url
            seen["headers"] = kw.get("headers")
            return _OKResp()

        monkeypatch.setattr(health.httpx, "get", fake_get)
        monkeypatch.setenv("GROK_API_KEY", "test-key-123")
        statuses = health.check_all(cfg_path)
        grok = next(s for s in statuses if s.name == "grok_api")
        assert grok.healthy is True
        # Last ping is Grok; it must carry the Bearer token (else xAI 401s).
        assert seen["headers"]["Authorization"] == "Bearer test-key-123"
        assert seen["url"].endswith("/models")


class TestRequireHealthy:
    def test_raises_when_lm_studio_down(self, tmp_path, monkeypatch):
        cfg_path = _write_cfg(tmp_path, mode="offline")

        def boom(url, **kw):
            raise httpx.ConnectError(f"down {_LM_MODELS}")

        monkeypatch.setattr(health.httpx, "get", boom)
        with pytest.raises(LLMServiceError):
            health.require_healthy(cfg_path)

    def test_passes_when_lm_studio_up(self, tmp_path, monkeypatch):
        cfg_path = _write_cfg(tmp_path, mode="offline")
        monkeypatch.setattr(health.httpx, "get", lambda url, **kw: _OKResp())
        # Should not raise.
        health.require_healthy(cfg_path)


class TestHealthCfgCache:
    def test_cfg_parsed_once_per_path(self, tmp_path):
        cfg_path = _write_cfg(tmp_path)
        first = health._health_cfg(cfg_path)
        second = health._health_cfg(cfg_path)
        # Same object identity -> the second call was served from the cache.
        assert first is second
