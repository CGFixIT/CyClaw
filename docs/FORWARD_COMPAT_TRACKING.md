# Forward Compatibility Tracking

A lightweight index of known upstream deprecations and future migration paths, so
dependency-lifecycle changes don't surprise the team. Each entry links to the deeper
tech note where one exists; this file is the at-a-glance register, not the full analysis.

| Item | Status | Trigger to act | Detail |
|---|---|---|---|
| Starlette `TestClient` → `httpx2` | ⚠️ Informational (no runtime impact) | Next Starlette **major** bump | [`TESTCLIENT_HTTPX_DEPRECATION.md`](TESTCLIENT_HTTPX_DEPRECATION.md) |

---

## Starlette `TestClient` / `httpx2` deprecation

**Scope:** This is a **test-time only** concern. Starlette's `TestClient` (re-exported by
`fastapi.testclient`) emits a `StarletteDeprecationWarning` because it prefers the separate
`httpx2` distribution over the classic `httpx` line. Runtime `httpx` usage (e.g.
`llm/client.py` for LM Studio / Grok calls) does **not** touch `starlette.testclient` and is
unaffected — do not change the runtime `httpx==0.28.1` pin to "fix" this warning.

The warning text:

```
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
```

**Affected test code** (the only `TestClient` consumers):

- `tests/test_gate.py` — gateway integration tests
- `tests/test_security.py` — security / CORS tests

**Timeline:** Starlette is already 1.x in the current pins, so the `httpx`-1.x shim removal is
expected on a **future Starlette major**, not a "1.0" release. Until then the warning is
cosmetic and all tests pass.

**Migration is dependency-level, not test-rewrite-level:** the expected path is to install
`httpx2` so `TestClient` picks it up, then re-validate the two consuming test files — not to
edit `tests/test_*.py` to import `httpx2` directly. See the tech note for the full options
analysis (silence-the-warning vs. add `httpx2` vs. drop `TestClient` for an ASGI transport)
and the recommendation.

### Defensive pin (done)

- [x] Pin Starlette (`starlette==1.3.1`) explicitly in `requirements.txt` and `pyproject.toml`.
  FastAPI 0.137.2 requires `starlette>=0.46.0` with no upper bound, so without this pin a future
  Starlette major dropping the `httpx`-1.x shim could be pulled in silently and break
  `TestClient` import. `constraints.txt` already carried the pin transitively; it is now explicit
  in the human-maintained source-of-truth files too.

### Open action items

- [ ] **Monitor:** Watch dependabot PRs that move `starlette` past `1.x`.
- [ ] **Migrate:** When the Starlette major lands, add `httpx2` for the test client and
  re-validate `tests/test_gate.py` and `tests/test_security.py` (see tech note, Option 3).
