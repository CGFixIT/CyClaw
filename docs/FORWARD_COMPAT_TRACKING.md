# Forward Compatibility Tracking

CyClaw tracks known deprecations and future migration paths to stay ahead of dependency lifecycle changes.

## Starlette/httpx TestClient Deprecation

**Status:** ⚠️ Upcoming (not yet blocking)  
**Detected:** 2026-06-21 (Python 3.12 sandbox verification)  
**Source:** Starlette/FastAPI test suite warning

### Details

The test suite emits:
```
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; 
install `httpx2` instead.
```

**Current code:** FastAPI `TestClient` (via Starlette) pulls in `httpx`, which is deprecated  
**Migration path:** Starlette will remove the `httpx` shim; projects must migrate to `httpx2`

### Action Items

- [ ] **Monitor:** Track Starlette releases (>1.0) for the removal timeline
- [ ] **Test:** Verify `httpx2` compatibility with FastAPI/Starlette when available
- [ ] **Migrate:** Update `tests/test_*.py` to use `httpx2` instead of httpx (if Starlette removes the shim)
- [ ] **Pin:** Defensively pin Starlette version in `requirements.txt` until migration is complete

### Affected Code

- `tests/conftest.py` — `TestClient` fixture creation
- `tests/test_gate.py`, `tests/test_graph.py`, `tests/test_security.py` — TestClient usage
- `requirements.txt` — FastAPI + Starlette pinning

### Timeline

- **Now:** Warning is non-fatal; CI passes
- **6-12 months:** Starlette may release removal in 1.0+ (monitor releases)
- **Migration:** Update to `httpx2` when Starlette upstream guidance is clear

---

See also: [CyClaw Python Coding Agent](/.claude/README.md) forward-looking notes section.
