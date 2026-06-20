# CyClaw Runtime Verification Report

**Date:** 2026-06-20  
**Runtime:** Python 3.12  
**Branch:** claude/jolly-cerf-v0vbjz  
**Method:** Cold-start venv, 98-test suite, live RAG smoke, FastAPI TestClient probing, LangGraph path coverage, targeted security probes.

---

## Test Results

| Step | Result |
|------|--------|
| 98-test suite (sanitizer, rate limiter, logger, personality, graph, search, MCP, security, telemetry) | ✅ 98 passed, 0 failed |
| Real RAG smoke — ChromaDB + BM25 index built, live query, top score `0.050` > gate `0.028` | ✅ |
| `GET /health` | ✅ 200 OK (lm_studio degraded as expected, embeddings/index/graph healthy) |
| `POST /query` with injection payload → `400 PROMPT_INJECTION_BLOCKED` | ✅ |
| Rate limiter — request #60 hit `429 RATE_LIMIT` exactly | ✅ |
| LangGraph high-score → local LLM path | ✅ |
| LangGraph low-score + online → Grok fallback path | ✅ |
| LangGraph low-score + offline → best-effort path | ✅ |
| Soul `GET /soul`, `POST /soul/propose` | ✅ |
| Stemmer tech-vocabulary overrides (`Kubernetes→k8s`, `chromadb→chroma`) | ✅ |

---

## Findings & Suggested Fixes

### 🔴 Critical (Confirmed by Live Probe)

#### F1 — `/soul/apply` has no injection scan
**File:** `utils/personality.py:168`

`apply_evolution()` writes any content unconditionally. Live probe confirmed: `POST /soul/apply {"new_soul": "ignore previous instructions"}` returned `200 applied` and overwrote `soul.md`. The injection gate exists only in `propose_evolution()` — callers who POST directly to `/soul/apply` bypass it entirely.

**Fix:**
```python
# top of apply_evolution()
for pattern in OWASP_INJECTION_PATTERNS:
    if re.search(pattern, new_soul, re.IGNORECASE):
        raise ValueError(f"Injection pattern detected in soul content: {pattern!r}")
```
Mirror the check already present in `propose_evolution()` at line 145.

---

### 🟠 Medium

#### F2 — Raw BM25/cosine scores bypass RRF-calibrated `min_score` gate
**File:** `retrieval/hybrid_search.py:146`

When one retrieval path returns empty results, the fallback returns raw scores directly. BM25 scores are unbounded (often > 1.0); `min_score=0.028` is calibrated for RRF-fused scores. A degraded keyword-only response always clears the gate and is silently treated as a high-confidence vault hit, suppressing the Grok confirmation prompt.

**Fix:** Normalize single-path scores before returning, or apply RRF scoring even when one path is empty so the threshold remains meaningful.

#### F3 — Smoke test WARN doesn't fail CI
**File:** `tests/ci_rag_smoke.py:62`

When `EXPECTED_SOURCE_SUBSTR` is not in the top result's source, the test prints `WARN` but falls through to `return 0`. A retrieval regression ships undetected as long as the wrong document clears the score gate.

**Fix:**
```python
if EXPECTED_SOURCE_SUBSTR not in top.source:
    print(f"WARN: expected source not top result. Got: {top.source}")
    return 1  # fail CI
```

#### F4 — `grok_fallback_node` crashes on partial config
**File:** `graph.py:212`

`cfg["policy"]["fallback"]` raises `KeyError` when a hybrid-mode graph is constructed with a minimal config dict. Real usage is fine (full `config.yaml` always loaded), but test isolation is brittle — the CI suite silently avoids this by only building offline-mode graphs.

**Fix:** Use `.get()` with safe defaults: `cfg.get("policy", {}).get("fallback", {})`.

#### F5 — `"null"` string in CORS `allowed_origins`
**File:** `config.yaml:174`

The string `"null"` is a real browser `Origin:` header value sent by sandboxed `<iframe>` elements, `file://` pages, and `data:` URIs. Starlette matches it directly, permitting cross-origin requests from those contexts.

**Fix:** Remove the `- "null"` entry. curl and MCP clients send no `Origin` header and need no allowlist entry.

#### F6 — Timing attack on API key comparison
**File:** `gate.py:80`

Standard `!=` string comparison is not timing-safe.

**Fix:**
```python
import hmac
if not credentials or not hmac.compare_digest(credentials.credentials, api_key):
    raise HTTPException(status_code=403, detail="Invalid API key")
```

#### F7 — MCP server returns raw query text in response metadata
**File:** `mcp_hybrid_server.py:61`

`"metadata": {"query": query, ...}` contradicts the "never leak raw query text" invariant enforced by `audit_log()`.

**Fix:**
```python
from utils.logger import hash_query
"metadata": {"query_hash": hash_query(query), "retrieval_mode": mode, "total_results": len(results)}
```

#### F8 — FastAPI `/docs` and `/openapi.json` exposed
**File:** `gate.py` (FastAPI constructor)

Unnecessary schema disclosure — exposes all route shapes including `/soul/apply` payload format.

**Fix:**
```python
app = FastAPI(title="CyClaw RAG Gateway", docs_url=None, redoc_url=None, openapi_url=None)
```

#### F9 — `setuptools==70.2.0` below CVE-2024-6345 fix
**File:** `constraints.txt`

CVE-2024-6345 (CVSS 8.8, RCE) affects `setuptools < 70.3.0`.

**Fix:** Restore to `setuptools>=70.3.0` or the prior `82.0.1` pin.

#### F10 — `claude.yml` uses unpinned action refs with broad write permissions
**File:** `.github/workflows/claude.yml:23,29`

`actions/checkout@v4` and `anthropics/claude-code-action@beta` are floating tags. The workflow holds `contents: write`, `pull-requests: write`, `issues: write`, and `id-token: write`. A moved tag = arbitrary code execution with those permissions.

**Fix:** Pin both to full commit SHAs, matching the pattern already used in `ci.yml`.

---

### 🟡 Low / Robustness

#### F11 — `config.yaml` opened with CWD-relative path throughout
**Files:** `gate.py:151`, `llm/client.py`, `retrieval/hybrid_search.py`, `retrieval/embeddings.py`, `utils/sanitizer.py`

Works only because CWD happens to be the repo root. Breaks silently under systemd, Docker `WORKDIR`, or any CI step with `working-directory:` override.

**Fix:**
```python
CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
```

#### F12 — `build_index()` destroys and rebuilds on every call
**File:** `retrieval/indexer.py:89`

`delete_collection()` + `create_collection()` runs unconditionally, re-embedding all corpus chunks every CI run.

**Fix:** Add a `force=False` guard that checks collection existence before rebuilding.

#### F13 — `'urgent|action\s+required'` over-broad — blocks legitimate queries
**File:** `config.yaml:135`

`re.search` matches `urgent` anywhere with no word boundary. Blocks `"I need urgent medical advice"`, `"is this urgent?"`, etc.

**Fix:** Add `\b` anchors: `'\burgent\b.*\baction\s+required\b'`.

#### F14 — Dead injection pattern
**File:** `config.yaml:113`

`'act\s+as'` (line 112) fires first and raises. The specific pattern `'act\s+as\s+if\s+you\s+have\s+no\s+restrictions'` can never independently trigger, losing audit triage signal.

**Fix:** Remove the generic `act\s+as` or restructure so specific patterns are checked before generic ones.

#### F15 — No HTTP security headers
**File:** `gate.py`

Missing `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`.

**Fix:**
```python
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline' "
            "https://fonts.googleapis.com; font-src https://fonts.gstatic.com"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)
```

#### F16 — Meta tag values in terminal UI not HTML-escaped
**File:** `static/terminal.html:844`

`m.k` and `m.v` go raw into `innerHTML`. Answer text is correctly escaped via `escHtml()` but meta tags are not.

**Fix:**
```javascript
html += `<span class="meta-tag">${escHtml(String(m.k))}: <span class="val">${escHtml(String(m.v))}</span></span>`;
```

#### F17 — Soul content stored verbatim in SQLite with no filesystem permissions enforced
**File:** `utils/personality.py`

Every soul version stored in cleartext in `data/personality/cyclaw_soul.db` with no programmatic `chmod` on first run.

**Fix:** `os.chmod("data/personality/", 0o700)` on first run, or restrict at the directory level in setup docs.

#### F18 — `codeql.yml` / `devskim.yml` use unpinned action tags
**Files:** `.github/workflows/codeql.yml`, `.github/workflows/devskim.yml`

Use `@v4`/`@v6`/`@v7` floating tags while `ci.yml` correctly pins to SHAs.

**Fix:** Pin all action refs to full commit SHAs.

#### F19 — `id-token: write` in `claude.yml` may be unnecessary
**File:** `.github/workflows/claude.yml`

OIDC token generation enables cloud provider authentication. Evaluate whether `claude-code-action` requires it; remove if not.

---

### ℹ️ Informational

#### F20 — LM Studio unavailable → confusing inline error in UI
`/query` returns `"[LLM Error: LM Studio error: [Errno 111] Connection refused]"` in the `answer` field. First-time users without LM Studio running see this inline in the browser chat.

**Fix:** Return a user-friendly `"No LLM available — is LM Studio running?"` message when connection is refused.

#### F21 — `httpx` deprecation warning
FastAPI's `TestClient` warns to migrate to `httpx2`. Not urgent, but will eventually be breaking.

#### F22 — `package.json` references non-existent `index.js`; unused `express` dependency
No `index.js` exists. `express` adds unnecessary supply chain surface. Remove `"main"`, `"start"`, and `express` if `package.json` is only used for ESLint tooling.

---

## Verified Positive Controls

The following security controls were confirmed working correctly during live probing:

- ✅ DOM XSS: all LLM answer text passes through `escHtml()` before `innerHTML`
- ✅ Audit logs: query text SHA-256 hashed, never stored raw
- ✅ Secret redaction in HTTP error responses (`_sanitize_error()`)
- ✅ No hardcoded credentials — all secrets read from env vars
- ✅ BM25 pickle → JSON migration complete (prior RCE vector resolved)
- ✅ Soul writes are atomic (`os.replace()` with `.tmp` staging + `.bak` backup)
- ✅ SQLite queries fully parameterized — no SQL injection vectors
- ✅ `CORS allow_credentials=False`
- ✅ MCP server cannot invoke LLM (`sampling: None`)
- ✅ Telemetry kill-switch applied before chromadb/langchain imports
- ✅ Rate limiter enforces 60 req/min exactly
- ✅ Prompt injection gate blocks known payloads with `400 PROMPT_INJECTION_BLOCKED`
- ✅ NLTK `punkt` tokenizer bypassed (avoids path-traversal CVE)
- ✅ CI action SHAs pinned in `ci.yml`; `permissions: contents: read` applied
