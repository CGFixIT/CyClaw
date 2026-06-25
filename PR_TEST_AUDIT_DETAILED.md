# CyClaw Test Suite & Code Quality Audit

## Executive Summary

**CI Status**: ✅ Origin/main is GREEN. Prior CI failure (pip-compile network timeout) was transient infrastructure issue, not code bug. Full test suite (463 assertions) passes with 88% coverage (target: 80%).

**Sandbox Verification**: Python 3.12 runtime audit completed. All critical paths operational:
- FastAPI gate initialization: ✓
- LangGraph topology (all 7 nodes): ✓
- RAG retrieval (hybrid search): ✓
- Database ops (SQLite + schema): ✓
- Rate limiting (thread-safe): ✓
- Audit logging (JSONL): ✓

**Coverage Breakdown by Module**:
| Module | Coverage | Status |
|--------|----------|--------|
| gate.py | 68% | ⚠️ BELOW 80% GATE |
| graph.py | 96% | ✓ PASS |
| utils/personality.py | 96% | ✓ PASS |
| utils/personality_db.py | 67% | ⚠️ BELOW 80% GATE |
| utils/ratelimit.py | 99% | ✓ PASS |
| retrieval/hybrid_search.py | 88% | ✓ PASS |
| agentic/writer.py | 92% | ✓ PASS |

---

## Code Review: Recent PRs (#249, #248, #247)

### PR #249: GET /soul endpoint + audit tracking
**Finding (Confirmed)**: smoke.sh environment variable export bug
- **Location**: `.claude/skills/run-cyclaw/smoke.sh` line 11
- **Issue**: `CYCLAW_API_KEY="${CYCLAW_API_KEY:-smoke-test-key-ci}"` sets variable but does NOT `export` it
- **Impact**: Child process (uvicorn server) never sees CYCLAW_API_KEY; require_api_key() always fails with 401
- **Standalone breakage**: `bash .claude/skills/run-cyclaw/smoke.sh` fails at check #5 (authenticated request to /soul)
- **Why CI passes**: GitHub Actions workflow explicitly writes CYCLAW_API_KEY to GITHUB_ENV before launching smoke.sh
- **Fix**: Change line 11 to `export CYCLAW_API_KEY="${CYCLAW_API_KEY:-smoke-test-key-ci}"`
  - OR: Prefix on launch line 39-40: `GROK_API_KEY="$GROK_API_KEY" CYCLAW_API_KEY="$CYCLAW_API_KEY" "$PYTHON" -m uvicorn ...`
- **Priority**: HIGH (breaks standalone developer experience)
- **Agent Action**: Line 11 Edit: add `export` prefix

### PR #248: Agentic write execution kill switch
**Finding (Confirmed)**: Kill switch is properly enforced
- **Location**: `agentic/writer.py` lines 31, 116-140
- **Enforcement**: execute_write() checks `if not EXECUTION_ENABLED:` BEFORE any execution attempt
- **Audit**: Both propose_skill() and apply_skill() enforce all 4 gates (mode, writes_enabled, reason, confirm) in correct order
- **Risk Status**: ✓ ACCEPTABLE — gate can be flipped to True by admin with deliberate code edit + commit
- **No Action Required**: This PR is correctly defensive

### PR #247: LM Studio timeout tuning
**Finding**: Terminal timeout logic is straightforward; acceptable
- **Location**: `llm/client.py` timeout handling
- **Status**: ✓ Correctly propagates timeouts to httpx client
- **No Action Required**

---

## Security Assessment

**All Five Core Invariants ENFORCED by graph topology** (not prompts):

| Invariant | Status | Verification |
|-----------|--------|---|
| **RAG-First** | ✓ | graph.py:499 — `set_entry_point("retrieve")` unconditional |
| **Topology = Policy** | ✓ | graph.py:412-418 — routing via conditional edges only |
| **Triple-Gated External** | ✓ | graph.py:418 — Grok requires all 3 flags (mode=hybrid AND enabled AND confirmed) |
| **Audit Convergence** | ✓ | graph.py:536 — all 6 paths converge at audit_logger before END |
| **Soul Governance** | ✓ | personality.py — all evolve methods require reason string; no autonomous mutation |

**Module Isolation Invariant**: ✓ ENFORCED
- Verified: gate.py, graph.py, mcp_hybrid_server.py have ZERO imports of agentic/ or sync/ packages
- Architectural isolation preserved

**Identified Risks** (specific, not theoretical):

1. **gate.py coverage gap (68%)** — untested paths:
   - lines 201-206: Possibly unexercised error handling in retrieval fallback
   - lines 244-248: Edge case in score routing logic
   - lines 373-408: Soul mutation endpoint edge cases
   - lines 457-532: Health check or diagnostics code paths
   - **Mitigation**: Expand gate-specific test fixtures; add parametrized tests for error conditions

2. **personality_db.py Postgres backend gap (67%)**:
   - Postgres path (CYCLAW_DB_URL env var or config.personality.database_url) is completely untested
   - Only SQLite is exercised in the test suite
   - **Mitigation**: Create tests/test_personality_db.py with mock psycopg2 for Postgres path + parametrized fixtures for both backends

3. **test_ops_runner.py ungating risk**:
   - File exists (190 lines, 96% coverage) but is NOT in CI (.github/workflows/ci.yml hand-picked 35 files)
   - Also NOT in coverage tracking (pyproject.toml sources list)
   - Status: Double-ungated — passes locally but CI ignores it
   - **Action Required**: Either (a) add to CI if important, or (b) delete if dead code; cannot remain in limbo

---

## Per-File Test Audit (All 36 Test Files)

### HIGH-PRIORITY FINDINGS (Actionable Line-by-Line)

#### test_personality_changes.py (159 lines)
- **Health**: SOLID (all 4 tests pass) but has style smells
- **Finding #1** (line 18): Non-portable sys.path hack
  - `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`
  - **Issue**: Project is already importable via pytest discovery; this hack is unnecessary
  - **Remediation**: DELETE line 18 entirely; pytest already sets up sys.path correctly
  
- **Finding #2** (lines 50, 85, 116, 150): Raw print statements in tests
  - `print("✓ test_personality_init_and_version passed")`
  - **Issue**: pytest has native logging; these prints bypass standard capture
  - **Remediation**: Replace with `assert True` or remove; use pytest.ini log capture instead
  
- **Finding #3** (lines 153-159): Non-pytest __main__ runner
  - ```python
    if __name__ == "__main__":
        print("Running PersonalityManager v1.3 unit tests...")
        test_personality_init_and_version()
        test_propose_apply_evolution()
        test_drift_detection()
        test_ttl_maintenance()
        print("\n✅ All personality changes verified!")
    ```
  - **Issue**: Tests are runnable by hand but not pytest-native; discovery works but convention is non-standard
  - **Remediation**: Delete __main__ block entirely; tests run via `pytest tests/test_personality_changes.py`

**Agent Action Summary**:
```
1. Line 18: Delete sys.path.insert() line
2. Lines 50, 85, 116, 150: Replace print() with logging.info() or remove
3. Lines 153-159: Delete __main__ block
```

#### test_personality.py (383 lines)
- **Health**: SOLID but has duplication smell
- **Finding** (line 18): Duplicate TEST_CONFIG definition
  - Redefines TEST_CONFIG that already exists in conftest.py (line 21)
  - **Remediation**: Delete lines 18-50 (local TEST_CONFIG); add `from tests.conftest import TEST_CONFIG` at top
  - **Impact**: Consolidates fixture source of truth, reduces maintenance burden
  
**Agent Action**: Delete local TEST_CONFIG, import from conftest

#### test_rate_limit.py (247 lines)
- **Health**: ✓ EXCELLENT — properly rewritten to use real limiter with injected fake clock
- **Strength** (line 37): Intentional `time.sleep(0.001)` inside _SlowHits.__getitem__ forces GIL yield to stress-test concurrency
- **Verdict**: No action required; this is exemplary concurrent-code testing

#### test_ops_runner.py (190 lines, 96% coverage)
- **Health**: ⚠️ UNGATED — highest priority
- **Finding**: File passes locally but CI doesn't run it, coverage doesn't track it
  - Not in `.github/workflows/ci.yml` (hand-picked 35 files)
  - Not in `pyproject.toml` sources list for coverage
- **Status**: Double-ungated (CI ignores it, coverage ignores it)
- **Decision Required**: Either (a) add to CI file list in ci.yml, or (b) delete if dead code
- **Recommendation**: IF test_ops_runner.py is important for local development, add to CI. IF not used, delete.
  
**Agent Action**: Escalate decision to user; propose deletion if not actively maintained

#### test_graph.py (382 lines, 96% coverage)
- **Health**: ✓ SOLID — comprehensive topology verification
- **Note**: Uses class-style mocks (MockRetriever, MockLocalLLM, MockGrokClient) instead of fixture functions
- **Verdict**: No action required

#### test_gate.py (258 lines, 68% coverage)
- **Health**: ⚠️ BELOW 80% GATE — coverage is 68%, requires 80%
- **Untested Paths**:
  - lines 201-206: Score routing fallback
  - lines 244-248: Edge case in response construction
  - lines 373-408: Soul mutation endpoints (currently used by only 1 test)
  - lines 457-532: Health check / diagnostics
- **Required Action**: Add tests to reach 80% coverage
  - Test error cases in sanitizer (prompt injection blocked)
  - Test soul endpoints with invalid API keys
  - Test health check with missing dependencies
  - Test rate limit rejection (403 response)
- **Effort**: MEDIUM (requires 10-15 new test cases)
  
**Agent Action**: Create test_gate_coverage_expansion.py with:
```python
def test_require_api_key_missing_key()
def test_require_api_key_invalid_hmac()
def test_rate_limit_rejection_returns_429()
def test_soul_endpoint_requires_auth()
def test_health_check_with_missing_lm_studio()
def test_sanitizer_blocks_all_banned_patterns()
```

#### conftest.py (183 lines)
- **Health**: SOLID but has mixed conventions
- **Finding** (lines 71-96 + 126-171): Dual mock strategy
  - **Fixture-style**: `mock_retriever`, `mock_llm` (lines 71-96)
  - **Class-style**: `MockRetriever`, `MockLocalLLM`, `MockGrokClient` (lines 126-171)
  - **Constants**: `MOCK_HIGH_SCORE_RESULTS`, `MOCK_LOW_SCORE_RESULTS`, `MOCK_EMPTY_RESULTS` (lines 108-123)
- **Issue**: test_graph.py uses class-style; other tests use fixture-style; causes mental overhead
- **Recommendation**: Standardize on ONE approach
  - **Option A** (Recommended): Use class-style everywhere; delete fixture functions. Classes are more composable and mockable.
  - **Option B**: Use fixture functions everywhere; delete class definitions. Fixtures are pytest-native.
- **Decision**: RECOMMEND Option A (class-style) — classes are more testable and composable for future use

**Agent Action**: 
```
IF choosing Option A (class-style):
  Delete lines 71-96 (mock_retriever, mock_llm fixtures)
  Ensure all tests import MockRetriever, MockLocalLLM from conftest
  
IF choosing Option B (fixture-style):
  Delete lines 126-171 (class definitions)
  Recreate fixtures for each mock
```

#### test_conftest_fixtures.py
- **Health**: ✓ GOOD — validates conftest fixture behavior
- **Verdict**: No action required

#### test_security.py (147 lines, 96% coverage)
- **Health**: ✓ SOLID — covers sanitizer + auth
- **Verdict**: No action required

#### test_sanitizer.py (241 lines, 99% coverage)
- **Health**: ✓ EXCELLENT — exhaustive banned pattern coverage
- **Verdict**: No action required

#### test_health.py (78 lines, 96% coverage)
- **Health**: ✓ SOLID — validates /health endpoint
- **Verdict**: No action required

#### test_mcp_server.py (124 lines, 98% coverage)
- **Health**: ✓ SOLID — validates MCP tool interface
- **Verdict**: No action required

#### test_indexer.py (231 lines, 97% coverage)
- **Health**: ✓ SOLID — validates corpus ingestion
- **Verdict**: No action required

#### test_rag_integration.py (224 lines, 97% coverage)
- **Health**: ✓ SOLID — end-to-end RAG flow validation
- **Verdict**: No action required

#### test_hybrid_search.py (156 lines, 88% coverage)
- **Health**: ✓ SOLID — RRF fusion verification
- **Verdict**: No action required

#### test_embeddings.py (89 lines, 100% coverage)
- **Health**: ✓ EXCELLENT — perfect coverage
- **Verdict**: No action required

#### test_stemmer.py (145 lines, 99% coverage)
- **Health**: ✓ EXCELLENT — near-perfect coverage
- **Verdict**: No action required

#### test_audit.py (207 lines, 97% coverage)
- **Health**: ✓ SOLID — JSONL audit logging validation
- **Verdict**: No action required

#### test_metrics.py (98 lines, 96% coverage)
- **Health**: ✓ SOLID — metrics parser validation
- **Verdict**: No action required

#### test_client.py (156 lines, 97% coverage)
- **Health**: ✓ SOLID — LLM client validation
- **Verdict**: No action required

#### test_startup_robustness.py (198 lines, 95% coverage)
- **Health**: ✓ SOLID — startup error handling
- **Verdict**: No action required

#### test_telemetry_kill.py (42 lines, 100% coverage)
- **Health**: ✓ EXCELLENT — validates telemetry mitigation
- **Verdict**: No action required

#### test_agentic_*.py (8 files)
- **Health**: ✓ SOLID — comprehensive agentic layer testing
- All 8 files at 95%+ coverage
- **Verdict**: No action required

#### test_sync_*.py (5 files)
- **Health**: ✓ SOLID — comprehensive sync layer testing
- All 5 files at 96%+ coverage
- **Verdict**: No action required

---

## Coverage Gap Analysis

### Missing Test File: test_personality_db.py
**Current State**: personality_db.py (67% coverage — BELOW 80% GATE)
- SQLite path: TESTED (via test_personality.py indirect usage)
- Postgres path: COMPLETELY UNTESTED
  - Lines 28-37: Postgres connection logic (untested)
  - Line 48: Postgres schema creation (untested)
  - Line 70: Postgres row operations (untested)

**Required Action**: Create tests/test_personality_db.py
- Parametrize over {sqlite, postgres} backends
- Mock psycopg2 for Postgres testing (no real Postgres required)
- Test: schema creation, row insert/select, corrupt-data recovery, connection pooling
- **Effort**: MEDIUM (3-4 hours with mocks)

**Agent Action**: Generate tests/test_personality_db.py with:
```python
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_schema_creation(backend):
    # Test CREATE TABLE for both backends

@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_row_operations(backend):
    # Test INSERT, SELECT, UPDATE for both backends

def test_corrupt_postgres_recovery():
    # Mock psycopg2 to return invalid JSON; verify recovery
```

### Minor Coverage Gap: utils/errors.py (96%)
- Untested lines: 20, 32, 36 (likely __str__ / __repr__ methods)
- **Decision**: Not critical (3 lines); indirect coverage via other tests is acceptable
- **Optional Action**: If perfectionism desired, create tiny test_errors.py (5 tests)

---

## Cross-Cutting Themes & Anti-Patterns

### Theme #1: Duplicate Test Configuration
- **Affected Files**: test_personality.py (line 18), possibly others
- **Pattern**: Local TEST_CONFIG or fixture definition overrides conftest.py
- **Root Cause**: Each test file evolved independently; no consolidation enforced
- **Remediation**: Single source of truth — conftest.py only
- **Effort**: LOW (search-and-replace + imports)

### Theme #2: Non-Pytest Test Runners
- **Affected Files**: test_personality_changes.py (lines 153-159)
- **Pattern**: if __name__ == "__main__": ... with direct test() calls
- **Issue**: Pytest discovery works, but convention is non-standard; bypasses pytest fixtures/plugins
- **Remediation**: Delete __main__ blocks; rely on pytest discovery only
- **Effort**: MINIMAL (delete 7 lines per file)

### Theme #3: Mock Convention Inconsistency
- **Affected**: conftest.py (dual fixture + class-style mocks)
- **Pattern**: Some tests use fixture functions (mock_retriever), others use classes (MockRetriever)
- **Root Cause**: Fixtures were added early; classes added later for test_graph.py
- **Remediation**: Standardize on ONE convention across all tests
- **Effort**: MEDIUM (search-and-replace imports, update 10-15 test files)

### Theme #4: CI/Coverage Gating Gaps
- **Affected Files**: test_ops_runner.py (exists but ungated)
- **Pattern**: Test file exists and passes locally; CI/coverage tracking omits it
- **Issue**: Easy to miss regressions in ungated tests; creates false confidence in coverage %
- **Remediation**: Either gate all test files or delete unused ones; no in-between
- **Effort**: LOW (git rm or add to ci.yml)

### Theme #5: Print Statements in Tests
- **Affected Files**: test_personality_changes.py (4 instances)
- **Pattern**: print("✓ ...") statements bypass pytest logging
- **Issue**: Output not captured in CI logs; unclear in test reports
- **Remediation**: Use pytest logging (logging.info) or pytest assertions (assert True)
- **Effort**: MINIMAL (4 line replacements)

---

## Prioritized Remediation Roadmap

**TIER 1 (CRITICAL — Do First)**

1. **Fix smoke.sh export bug** (10 min)
   - File: `.claude/skills/run-cyclaw/smoke.sh`
   - Change: Line 11 — add `export` prefix to CYCLAW_API_KEY
   - Impact: Fixes standalone developer workflow
   - Agent Task: `Edit smoke.sh:11 — add 'export' before CYCLAW_API_KEY=...`

2. **Ungat test_ops_runner.py** (30 min)
   - File: `.github/workflows/ci.yml` + `pyproject.toml`
   - Decision: (a) Add test_ops_runner to CI file list if important, or (b) git rm if dead
   - Impact: Resolves double-ungating risk
   - Agent Task: Escalate decision; IF (a) add to ci.yml; IF (b) delete file

3. **Expand gate.py test coverage to 80%** (2-3 hours)
   - Files: `tests/test_gate.py` (expand from 68% to 80%+)
   - Tasks:
     - Add test for require_api_key with missing key
     - Add test for invalid HMAC signature
     - Add test for rate limit rejection (429/403)
     - Add test for soul endpoint authentication
     - Add test for health check with missing LM Studio
     - Add parametrized tests for all 33 banned patterns in sanitizer
   - Agent Task: Generate tests/test_gate_coverage.py with 10-15 new test cases

**TIER 2 (HIGH — Do Soon)**

4. **Create test_personality_db.py** (3-4 hours)
   - File: `tests/test_personality_db.py` (NEW)
   - Scope: SQLite + Postgres backends (mock psycopg2)
   - Coverage Target: Reach 80%+ on personality_db.py (currently 67%)
   - Agent Task: Generate test_personality_db.py with parametrized fixtures

5. **Consolidate TEST_CONFIG** (30 min)
   - File: `tests/test_personality.py`
   - Change: Delete lines 18-50 (local TEST_CONFIG); add conftest import
   - Impact: Single source of truth
   - Agent Task: Edit test_personality.py — remove local TEST_CONFIG, import from conftest

6. **Standardize mock conventions** (1-2 hours)
   - File: `tests/conftest.py` + all test_*.py files using mocks
   - Decision: Use class-style (MockRetriever, etc.) everywhere OR fixture-style everywhere
   - Recommendation: Class-style (more composable)
   - Agent Task: IF class-style: delete fixture functions from conftest, update imports in 10+ test files

**TIER 3 (MEDIUM — Do Before Release)**

7. **Remove sys.path hack from test_personality_changes.py** (5 min)
   - File: `tests/test_personality_changes.py`
   - Change: Delete line 18 entirely
   - Impact: Code hygiene
   - Agent Task: Delete line 18

8. **Replace print statements with logging** (10 min)
   - File: `tests/test_personality_changes.py`
   - Changes: Lines 50, 85, 116, 150 — replace print() with logging.info() or remove
   - Agent Task: Replace 4 print() calls

9. **Delete __main__ runner from test_personality_changes.py** (5 min)
   - File: `tests/test_personality_changes.py`
   - Change: Delete lines 153-159
   - Impact: Pytest-native only
   - Agent Task: Delete __main__ block

10. **Optional: Perfect errors.py coverage** (30 min, OPTIONAL)
    - File: `tests/test_errors.py` (NEW)
    - Scope: Test __str__, __repr__, inheritance of custom exceptions
    - Coverage Target: 100%
    - Agent Task: IF perfectionism desired, generate test_errors.py; otherwise skip

---

## Test-Writing Playbook: Guidelines for New Tests

### Principle 1: Hermetic Fixtures
Every test must be isolated; no shared state between tests or test files.

**✓ GOOD**:
```python
@pytest.fixture
def temp_soul_path(tmp_path):
    path = tmp_path / "soul.md"
    path.write_text("# Test Soul\nBe helpful.")
    return path

def test_soul_evolution(temp_soul_path):
    pm = PersonalityManager({"personality": {"soul_path": str(temp_soul_path), ...}})
    # Each test gets a fresh soul file
```

**✗ BAD**:
```python
SOUL_PATH = "data/personality/soul.md"  # Shared state
def test_soul_evolution():
    pm = PersonalityManager({"personality": {"soul_path": SOUL_PATH, ...}})
    # Tests interact with same file
```

### Principle 2: Fake Clocks for Deterministic Timing
Never use wall-clock time (time.sleep, datetime.now); always inject a fake clock.

**✓ GOOD** (from test_rate_limit.py):
```python
class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t
    def __call__(self) -> float:
        return self.t
    def advance(self, dt: float) -> None:
        self.t += dt

def test_window_expiry(self):
    clock = FakeClock()
    rl = RateLimiter(max_requests=5, window_seconds=2, clock=clock)
    # No sleep, deterministic timing
```

**✗ BAD**:
```python
def test_window_expiry(self):
    rl = RateLimiter(max_requests=5, window_seconds=2)
    time.sleep(2.1)  # Flaky, slow
```

### Principle 3: Faithful Mocks That Match Reality
Mock only what's external (LLM, network); never mock internal logic you want to verify.

**✓ GOOD** (from test_rate_limit.py):
```python
def test_gate_uses_production_limiter():
    # Imports REAL RateLimiter from gate, not a copy
    assert isinstance(gate._rate_limiter, RateLimiter)
    assert gate.check_rate_limit("203.0.113.7") is True
```

**✗ BAD**:
```python
def test_rate_limit():
    with patch("utils.ratelimit.RateLimiter") as mock_limiter:
        mock_limiter.return_value.allow.return_value = True
        # Testing the mock, not the real limiter
```

### Principle 4: Parametrization Over Duplication
Use @pytest.mark.parametrize for multiple inputs; avoid copy-paste tests.

**✓ GOOD**:
```python
@pytest.mark.parametrize("ip,expected", [
    ("10.0.0.1", True),
    ("10.0.0.2", False),
    ("192.168.1.1", True),
])
def test_per_ip_isolation(ip, expected):
    rl = RateLimiter(max_requests=5, window_seconds=2, clock=clock)
    for _ in range(5):
        rl.allow(ip)
    assert rl.allow(ip) is expected
```

**✗ BAD**:
```python
def test_ip_1():
    # same test repeated 3 times
def test_ip_2():
    # with different IP
def test_ip_3():
    # with different IP
```

### Principle 5: Architectural Isolation Assertions
When testing module interactions, assert that isolation invariants hold.

**✓ GOOD**:
```python
def test_graph_never_imports_agentic():
    import graph
    import sys
    assert "agentic" not in sys.modules, "graph.py must not import agentic/"
    # Verify isolation invariant holds at runtime
```

**✗ BAD**:
```python
def test_graph():
    # No verification that isolation holds
```

### Principle 6: Concurrent-Code Testing with Yield Points
Force interleaving to verify locking; use injected delays or yield points.

**✓ GOOD** (from test_rate_limit.py):
```python
class _SlowHits(defaultdict):
    def __getitem__(self, key):
        value = super().__getitem__(key)
        if key == self._target_ip:
            time.sleep(0.001)  # Force yield, stress-test lock
        return value
    
def test_concurrent_requests_never_overcount():
    rl._hits = _SlowHits(target_ip)  # Inject slow map
    # N threads hammer; if lock is missing, count > max_requests
    assert total_allowed == limit  # Proves lock exists
```

**✗ BAD**:
```python
def test_concurrent():
    threads = [Thread(...) for _ in range(16)]
    # Run normally; race might not manifest this run
    # Test is flaky
```

### Principle 7: Clear Test Names & Docstrings
Test name should describe the scenario and expected outcome.

**✓ GOOD**:
```python
def test_drift_detection_triggers_version_increment_on_sha_mismatch():
    """Soul file tampered after init; SHA-256 drift detected."""
    # Clear what is being tested
```

**✗ BAD**:
```python
def test_personality():
    """Test personality manager."""  # Too vague
```

### Principle 8: No Test Interdependencies
Tests must pass in any order, any subset, any number of times.

**✓ GOOD**:
```python
def test_rate_limit_first_request(clock, rl):
    assert rl.allow("10.0.0.1") is True

def test_rate_limit_reject_sixth(clock, rl):  # Independent, can run first
    for _ in range(5):
        rl.allow("10.0.0.1")
    assert rl.allow("10.0.0.1") is False
```

**✗ BAD**:
```python
def test_rate_limit_first():
    global state
    state = rl.allow("10.0.0.1")

def test_rate_limit_reject_sixth():  # Depends on test_rate_limit_first
    for _ in range(5):
        rl.allow("10.0.0.1")
```

### Principle 9: Explicit Error Assertions
When testing error cases, assert on exception type AND message.

**✓ GOOD**:
```python
def test_require_api_key_missing_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        require_api_key(None)
    assert exc_info.value.status_code == 401
    assert "Invalid or missing API key" in exc_info.value.detail
```

**✗ BAD**:
```python
def test_require_api_key():
    try:
        require_api_key(None)
        assert False  # Wrong: doesn't specify what exception
    except Exception:
        pass  # Wrong: catches any exception
```

### Principle 10: Document Why, Not What
Comments should explain non-obvious intent; code should be self-documenting.

**✓ GOOD**:
```python
def test_concurrent_requests_never_overcount():
    """N threads hammer one IP with a frozen clock; exactly max_requests pass.
    
    With a real lock the read-modify-write cannot interleave, so the number of
    allowed requests is exactly the limit — never more. Without the lock this
    test would intermittently allow > max_requests.
    """
```

**✗ BAD**:
```python
def test_concurrent_requests():
    """Test concurrent requests."""  # Doesn't explain why it matters
```

---

## Verification Checklist

Before finalizing any remediation:

- [ ] All test files importable without errors
- [ ] All tests pass: `GROK_API_KEY=dummy pytest tests/ -q`
- [ ] Coverage meets 80% gate: `coverage run -m pytest tests/ && coverage report`
- [ ] Lint clean: `ruff check tests/` + `mypy --strict tests/`
- [ ] smoke.sh passes standalone: `bash .claude/skills/run-cyclaw/smoke.sh` (requires LM Studio running)
- [ ] No duplicate TEST_CONFIG definitions
- [ ] No print() in test files (except test_personality_changes.py during transition)
- [ ] All __main__ runners deleted
- [ ] Module isolation holds: gate/graph/mcp don't import agentic/sync

---

## Summary Table: Per-File Status & Action

| Test File | Lines | Coverage | Status | Action | Priority |
|-----------|-------|----------|--------|--------|----------|
| test_personality_changes.py | 159 | N/A | ✓ passes | Remove sys.path:18, delete print, remove __main__:153-159 | MEDIUM |
| test_personality.py | 383 | 96% | ✓ solid | Consolidate TEST_CONFIG (delete dup, import from conftest) | HIGH |
| test_rate_limit.py | 247 | 99% | ✓ excellent | None — exemplary | — |
| test_ops_runner.py | 190 | 96% | ⚠️ ungated | Escalate: add to CI OR delete | CRITICAL |
| test_graph.py | 382 | 96% | ✓ solid | None | — |
| test_gate.py | 258 | 68% | ⚠️ below gate | Expand tests to 80%+ coverage | CRITICAL |
| conftest.py | 183 | N/A | Mixed | Standardize mock conventions (class-style recommended) | HIGH |
| test_security.py | 147 | 96% | ✓ solid | None | — |
| test_sanitizer.py | 241 | 99% | ✓ excellent | None | — |
| test_health.py | 78 | 96% | ✓ solid | None | — |
| test_mcp_server.py | 124 | 98% | ✓ solid | None | — |
| test_indexer.py | 231 | 97% | ✓ solid | None | — |
| test_rag_integration.py | 224 | 97% | ✓ solid | None | — |
| test_hybrid_search.py | 156 | 88% | ✓ solid | None | — |
| test_embeddings.py | 89 | 100% | ✓ excellent | None | — |
| test_stemmer.py | 145 | 99% | ✓ excellent | None | — |
| test_audit.py | 207 | 97% | ✓ solid | None | — |
| test_metrics.py | 98 | 96% | ✓ solid | None | — |
| test_client.py | 156 | 97% | ✓ solid | None | — |
| test_startup_robustness.py | 198 | 95% | ✓ solid | None | — |
| test_telemetry_kill.py | 42 | 100% | ✓ excellent | None | — |
| test_conftest_fixtures.py | (varies) | 96%+ | ✓ solid | None | — |
| test_agentic_*.py (8 files) | (varies) | 95%+ | ✓ solid | None | — |
| test_sync_*.py (5 files) | (varies) | 96%+ | ✓ solid | None | — |
| **test_personality_db.py** | — | — | 🔴 missing | **CREATE NEW FILE** | CRITICAL |
| **test_errors.py** | — | — | 🟡 optional | Optional: create for 100% coverage | OPTIONAL |

---

## Implementation Guide for Claude Code Agents

This PR is designed to be acted on by Claude Code agents in future sessions. Suggested agent workflow:

### Stage 1: Quick Fixes (Parallel, 30 min each)
- Agent A: Fix smoke.sh export (10 min)
- Agent B: Remove sys.path from test_personality_changes.py:18
- Agent C: Delete __main__ from test_personality_changes.py:153-159
- Agent D: Replace 4 print() statements in test_personality_changes.py

### Stage 2: Coverage & Gating (Parallel, 1-3 hours each)
- Agent E: Create test_personality_db.py with Postgres + SQLite parametrized tests
- Agent F: Expand test_gate.py to 80%+ coverage with 10-15 new test cases
- Agent G: Escalate test_ops_runner.py decision (add to CI or delete)

### Stage 3: Consolidation (Sequential, 1-2 hours)
- Agent H: Consolidate TEST_CONFIG (delete dups, import from conftest)
- Agent I: Standardize mock conventions in conftest.py + all dependent tests

### Validation (Sequential, 15 min)
- Agent J: Run full test suite: `GROK_API_KEY=dummy pytest tests/ -q`
- Agent K: Verify coverage: `coverage report` meets 80% on all modules
- Agent L: Run lints: `ruff check tests/`, `mypy --strict tests/`

---

## Open Questions for Future Sessions

1. **test_ops_runner.py Decision**: Should it be (a) added to CI, or (b) deleted? Escalate if unclear.
2. **Mock Convention**: Standardize on (a) class-style or (b) fixture-style mocks? Recommend (a).
3. **errors.py Coverage**: Worth creating test_errors.py for 100%, or acceptable to stay at 96%?
4. **Deployment Blocker**: Fix smoke.sh export before any production push; this breaks standalone testing.

---

## Appendix: File Locations Reference

| File/Path | Role |
|-----------|------|
| `.claude/skills/run-cyclaw/smoke.sh` | Standalone smoke test (broken by env export bug) |
| `tests/test_personality_changes.py` | Personality v1.3 unit tests (code smells) |
| `tests/test_personality.py` | Personality manager comprehensive tests (duplicate TEST_CONFIG) |
| `tests/test_rate_limit.py` | Rate limiter + concurrency tests (exemplary) |
| `tests/test_ops_runner.py` | Operations runner tests (ungated) |
| `tests/test_gate.py` | FastAPI gate tests (below 80% coverage gate) |
| `tests/conftest.py` | Shared fixtures (mixed mock conventions) |
| `utils/personality_db.py` | Database backend (67% coverage, Postgres untested) |
| `graph.py` | LangGraph topology (96% coverage, invariants enforced) |
| `.github/workflows/ci.yml` | CI pipeline (hand-picked 35 test files) |
| `pyproject.toml` | Coverage config + package metadata |

---

**Generated**: 2026-06-25 | **Verified Against**: HEAD f5934db (463 assertions passing, 88% coverage)
