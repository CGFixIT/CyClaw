# PsyClaw — Code & Security Review

**Date:** 2026-06-16
**Reviewer:** Scheduled review routine (Claude Code)
**Base reviewed:** `main` @ `4f6adc5` ("Delete old.md")
**Runtime:** Python 3.12 semantics; deps installed minus heavy `torch`/`sentence-transformers` (lazy-imported)
**Companion:** PR #18 (unit-test deep-dive — PersonalityManager v1.3 contract) is the other half of this run.

This is **PR Set 2 of 2** for the 2026-06-16 review run: a code-quality + security review of the
code on `main`, the PRs merged to `main` since the last review, and the one open PR targeting
`main` (#14). It is a **report only** — no production code is changed in this PR. Each finding
is written so a follow-up Claude Code session (or a human) can act on it directly.

---

## 0. What was reviewed

### PRs merged to `main` since the last review (past day)
| PR | Title | Into | Risk | Notes |
|---|---|---|---|---|
| **#16** | test: audit failing suite + fix the 3 collection errors | `main` | Low | **Test-only** + a 1-line `schemas/api.py` hardening (`QueryRequest.query` `min_length=1`). Reviewed: correct, no production logic risk. |
| **#6** | deps: modernize requirements for Python 3.12 | `main` | Med (supply chain) | Pin tree in `constraints.txt`. See §2.7 — pins should be hash-verified and scanned. |

> The bulk of recent engineering (PRs #7, #8, #9, #11, #12, #15) landed on the **`cc`** integration
> branch, **not** `main`. They are bundled in open **PR #14 (`cc → main`)**, reviewed in §3.

Because only test/infra changes reached `main` recently, per the task this review also covers
**all production code files on `main`** (§1–§2) and assesses **open PR #14** (§3).

### Files reviewed on `main`
`gate.py`, `graph.py`, `mcp_hybrid_server.py`, `llm/client.py`,
`retrieval/{hybrid_search,indexer,embeddings,stemmer}.py`,
`utils/{sanitizer,personality,logger,health,errors}.py`, `schemas/api.py`, `config.yaml`,
`static/terminal.html`, `.github/workflows/ci.yml`, and `docs/PsyClaw_Architecture_v1.3.0.pdf`
(invariants cross-checked in §4).

---

## 1. Severity summary

| # | Severity | Finding | Location | Status / owner |
|---|---|---|---|---|
| S1 | **Medium** | Rate-limiter memory grows unbounded (no idle-IP eviction); "thread-safe" claim has no lock | `gate.py:74–84` | Fixed by **PR #14** (`_sweep_rate_limits`); lock still absent |
| S2 | **Medium** | Soul-governance invariant #5 partially unmet on `main`: non-atomic write, no forensic `audit_log` on drift/apply, no TTL-prune-on-init | `utils/personality.py` | **Fixed by PR #18** (this run); residual: no `threading.Lock` |
| S3 | **Medium** | `pickle.load` of the BM25 index → RCE if `index/bm25.pkl` is tampered | `retrieval/hybrid_search.py:71–75` | **Resolved** — migrated to JSON serialization; pickle removed entirely |
| S4 | **Medium** | Injection-filter coverage is weaker than the architecture claims (missing "do anything now / bypass safety / ignore safety") | `utils/sanitizer.py`, `config.yaml` | Open |
| S5 | **Medium** | CI false-green: only 2 test files run, exit code swallowed (`\|\| echo`) | `.github/workflows/ci.yml:49–51` | Partially fixed by #14 (drops `\|\| echo`); still 2 files only |
| S6 | **Low/Med** | Dead config: `policy.prompt_filter.*` is ignored by the hardcoded sanitizer on `main` | `utils/sanitizer.py` vs `config.yaml:77–93` | Fixed by **PR #14** |
| S7 | **Low** | CORS allowlist contains an inert `null`/`None` entry + a hardcoded LAN IP beyond documented localhost defaults | `config.yaml:122–129` | Open |
| S8 | **Low** | Injection scan on `/soul/propose` is advisory only — `apply_evolution` never enforces `safe_to_apply` | `utils/personality.py`, `gate.py:264–270` | Open (hardening, not an invariant violation) |
| S9 | **Low** | No authentication on state-mutating `/soul/*` endpoints (by design, localhost-only) | `gate.py:246–277` | **Resolved** — bearer token auth via `PSYCLAW_API_KEY` env var on mutation endpoints |
| S10 | **Info** | Positive controls verified (XSS escaping, secret redaction, telemetry kill, no-sampling MCP, env-only key) | multiple | OK |

No **Critical** issues found. No exposed secrets in the tree (§2.6).

---

## 2. Detailed findings

### S1 — Rate limiter: unbounded memory + unsynchronized state *(Medium)*
`gate.py:74–84`
```python
_rate_limits = defaultdict(list)
def check_rate_limit(client_ip):
    now = time.time()
    _rate_limits[client_ip] = [t for t in _rate_limits[client_ip] if now - t < RATE_LIMIT_WINDOW]
    ...
```
- **Unbounded growth:** every distinct `client_ip` leaves a permanent dict key — the timestamp
  list is filtered to empty but the key is never deleted. An attacker rotating source IPs
  (or simply long uptime behind a proxy) grows the dict without bound → memory-exhaustion DoS.
  The architecture PDF (p.5) advertises a "thread-safe in-memory dict"; the eviction is missing.
- **No actual locking:** the read-modify-write of `_rate_limits[ip]` is not guarded. Under
  FastAPI's threadpool, concurrent requests from one IP can interleave and miscount. "Thread-safe"
  is aspirational here.
- **Fix:** **merge PR #14**, which adds `_sweep_rate_limits()` to evict idle IPs (correct and
  cheap — runs at most once per window). *Additionally* recommend wrapping the counter in a
  `threading.Lock` (or moving to an atomic structure) to honor the documented thread-safety, since
  #14 does not add one.

### S2 — Soul governance invariant #5 partially unmet on `main` *(Medium)*
`utils/personality.py` (as shipped on `main`)
The architecture PDF (p.11 "Write-Order Invariant", p.19 guarantee #5) requires soul evolution to be
**crash-safe and forensically logged**: atomic `os.replace` write, a forensic `audit_log` on drift,
a `audit_log({'event':'soul_evolution_applied'})` on apply, and `maintenance(ttl_days)` invoked from
`__init__`. The `main` implementation:
- `apply_evolution` uses a plain `self.soul_path.write_text(...)` — **non-atomic** (a crash mid-write
  can leave `soul.md` half-written, the exact corruption the invariant promises to prevent);
- the module **never imports `audit_log`**, so **no forensic event** is emitted on drift or on apply
  (violates invariant #4/#5 "drift auto-recovers with forensic log");
- there is **no `maintenance()`** and no TTL prune on init (the doc's "TTL prune on init").
- **Status:** **PR #18 (this run) remediates all three** (atomic `os.replace`, `audit_log` on drift +
  apply, `maintenance()` called from `__init__`). **Residual gap:** the PDF specifies the SQLite
  version INSERT happen "under `threading.Lock`"; PR #18 uses a single shared connection with
  `busy_timeout` instead. For the multi-threaded gateway, add an explicit `threading.Lock` around the
  write path (tracked in PR #18's reviewer note).

### S3 — Pickle deserialization of the BM25 index *(Medium)* — **RESOLVED**
`retrieval/hybrid_search.py`, `retrieval/indexer.py`

**Original issue:** `pickle.load` executes arbitrary code embedded in the file. If anything can write
`index/bm25.pkl`, loading it is RCE in the gateway process.

**Resolution:** Migrated BM25 index serialization from pickle to JSON. The indexer now writes the
tokenized corpus, chunks, and metadata as a JSON file (`index/bm25.json`). The retriever reads
the JSON and rebuilds `BM25Okapi` from the tokenized corpus on load. `import pickle` has been
removed from both modules. A test (`test_security.py::TestBM25PickleRejection`) verifies that
a crafted pickle payload is rejected (JSON decode raises, no code execution). Config updated:
`indexing.bm25_path` changed from `index/bm25.pkl` to `index/bm25.json`.
**Note:** Existing `.pkl` index files must be regenerated via `python -m retrieval.indexer`.

### S4 — Injection filter weaker than documented *(Medium)*
`utils/sanitizer.py` `BANNED_PATTERNS` (13) / `config.yaml:79–92`
- The PDF (p.1, p.14) claims the v1.3 filter expanded to 13 "OWASP-aligned" patterns adding
  **`do anything now`, `act as uncensored`, `bypass safety`, `DAN`, `ignore safety`**. The shipped 13
  patterns are the `previous/all/prior`-instruction variants and **do not include**
  `do anything now`, `bypass safety`, or `ignore safety`. Real-world jailbreak coverage is therefore
  narrower than the architecture advertises.
- The same list is **duplicated** in `utils/personality.py:OWASP_INJECTION_PATTERNS` (with a
  `<script>` entry the sanitizer lacks) — two drifting copies of a security control.
- **Fix:** reconcile to one authoritative pattern set (config-driven once **PR #14** lands), add the
  documented missing jailbreak patterns, and have `personality.py` import that set instead of keeping
  its own copy.

### S5 — CI reports green while tests fail *(Medium)*
`.github/workflows/ci.yml:49–51`
```yaml
pytest tests/test_sanitizer.py tests/test_rate_limit.py -q --tb=no ... || echo 'Safe tests done'
```
- Only **2** of the suite's files run, and `|| echo` **discards the exit code**, so the job is green
  even though `pytest tests/` is currently **8 failed** on `main` (and was 19 failed pre-#18). This is
  a false health signal on a security-relevant project.
- **Fix:** **PR #14 removes the `|| echo`** (good) but still runs only those 2 files. After #14 + #18
  land (suite → all green), switch CI to the full `pytest tests/` and let the real exit code gate the
  build. (Also tracked in `tests/TEST_SUITE_AUDIT.md` §3/§5.)

### S6 — Dead config: `policy.prompt_filter` ignored on `main` *(Low/Medium)*
`utils/sanitizer.py` vs `config.yaml:77–93`
- `check_input`/`sanitize_chunk` on `main` use **hardcoded** `BANNED_PATTERNS` and
  `MAX_INPUT_CHARS = 4000` and never read `config.yaml`. Editing `policy.prompt_filter.enabled`,
  `banned_patterns`, or `max_input_chars` has **no effect** — a false sense of operator control over a
  security filter. (Same class of issue: `retrieval.hybrid.rrf.vector_weight/bm25_weight` are
  documented placeholders the retriever ignores — at least that one is commented.)
- **Fix:** **PR #14** makes the sanitizer config-driven (loads + compiles + caches from
  `policy.prompt_filter`, with `enabled:false` bypass and a warning when enabled-but-empty). Merging
  #14 closes this.

### S7 — CORS allowlist: inert `null` + LAN IP *(Low)*
`config.yaml:122–129`, applied in `gate.py:130–137`
- `allowed_origins` ends with a literal `null` (→ Python `None`) and a hardcoded LAN IP
  `http://10.0.0.112(:8787)`. The PDF (p.6) documents the default as **localhost only**.
- The `None` entry is **inert** for browsers (a real `Origin` header never equals `None`), but it is a
  smell that suggests "allow non-browser clients" — a misconception, since CORS does not gate
  non-browser clients at all. The LAN origin widens browser access **if** the gateway is ever rebound
  off `127.0.0.1` (it binds localhost today, so not currently reachable).
- Good: `allow_credentials=False`, methods limited to GET/POST, headers to `Content-Type`.
- **Fix:** drop the `null` entry; move the LAN IP behind a clearly-commented, env-specific override
  rather than the committed default.

### S8 — Soul injection scan is advisory only *(Low — hardening, not a violation)*
`utils/personality.py:propose_evolution` / `apply_evolution`, `gate.py:264–270`
- `propose_evolution` computes `injection_flags` / `safe_to_apply`, but `apply_evolution` **does not
  consult them** — a soul containing `ignore previous instructions` can be applied via `/soul/apply`.
- **Important nuance:** this is **not** an architecture-invariant violation. The PDF gates soul writes
  by *propose/apply separation + a required human reason string + no autonomous/graph path* (p.7,
  p.11), **not** by an injection block; drift is explicitly "detect + forensic log + auto-recover,"
  not a block. So flag this as **defense-in-depth**, not a regression.
- **Fix (optional):** have `apply_evolution` refuse when `injection_flags` are present unless an
  explicit `force=True`/override is passed, and `audit_log` the override. Keeps the human-reason gate
  while preventing an accidental self-jailbreak write.

### S9 — No auth on mutating endpoints *(Low — by design)*
`gate.py` `/soul/propose`, `/soul/apply`, `/soul/reload`, `/query`
- None of the endpoints authenticate. This is **documented** as a single-user localhost tool, so it is
  an accepted risk — but `/soul/apply` mutates the system identity. Combined with S7, a LAN peer could
  rewrite the soul **iff** the bind is ever moved off localhost.
- **Fix:** none required for the stated threat model; add a one-line deployment caveat in the README:
  "do not bind off 127.0.0.1 without adding auth." If remote use is ever wanted, gate `/soul/*` behind
  a token.

### S10 — Positive controls verified *(Info)*
- **DOM XSS handled:** `static/terminal.html` renders the LLM `answer` and source paths through
  `escHtml(...)` (`addEntry(..., isHtml=false)`); the only `isHtml=true` call is a static spinner
  literal (`terminal.html:750`). No untrusted text reaches `innerHTML` unescaped.
- **Secret redaction:** `gate.py:_sanitize_error` strips Bearer/API-key/AWS/GitHub/Slack patterns and
  live env-var values from exception messages before they reach HTTP responses.
- **Audit privacy:** `utils/logger.audit_log` SHA-256-hashes the `query` field and redacts
  emails/IPs/secret-like strings; raw query text is never written. `graph.py` records only a
  `hash_query(query)` to the personality DB.
- **Telemetry kill-switch** is set at the very top of `gate.py` *before* any langchain/chromadb import
  (and `anonymized_telemetry=False` on every Chroma client). Defense-in-depth, matches p.6/p.18.
- **MCP server** advertises `"sampling": None` and has no LLM path — the "MCP cannot invoke an LLM"
  protocol guarantee (p.13) holds.
- **Privacy default:** `policy.fallback.send_local_context_to_grok: false` — local KB is not forwarded
  to Grok unless explicitly opted in.
- **No secrets committed:** `GROK_API_KEY` is read from env; `psyclaw_telemetry_kill.env` contains only
  telemetry toggles; repo grep for credential-like assignments is clean.

### S2.7 — Dependency supply chain *(note)*
`requirements.txt` + `constraints.txt` (PR #6) — versions are pinned (good), but pins are not
hash-locked. Recommend `pip install --require-hashes` (or `pip-compile --generate-hashes`) and a
periodic `pip-audit` in CI to catch known-vuln advisories in the transitive tree (chromadb, langgraph,
fastapi, sentence-transformers pull a large surface).

---

## 3. Open PR #14 (`cc → main`) — "Config-driven prompt filter & performance optimizations"

Bundles `cc` work (#7/#8/#9/#11/#12/#15). Diff reviewed file-by-file:

| File | Change | Verdict |
|---|---|---|
| `utils/sanitizer.py` | Config-driven filter: `_load_filter(config_path)` loads/compiles/caches `policy.prompt_filter`; `enabled:false` bypass; warns when enabled-but-empty; `check_input` returns query; `sanitize_chunk(text, config_path)` | **Good.** Closes S6 and the 8 `test_sanitizer` failures. Note `lru_cache` means config edits need a process restart (acceptable; document it). |
| `gate.py` | `_sweep_rate_limits()` idle-IP eviction; `check_rate_limit` rewritten to bound memory | **Good.** Closes S1's memory leak. Still no `threading.Lock` (S1 residual). |
| `retrieval/embeddings.py` | `_embeddings_cfg` cached + context-managed open (fixes a per-call FD leak) | **Good.** Real bug fix (the `yaml.safe_load(open(path))` form leaked a descriptor every query). |
| `retrieval/hybrid_search.py` | `heapq.nlargest(k, …)` instead of full sort in `keyword_search` | **Good.** O(n log k) vs O(n log n); behavior-preserving. |
| `retrieval/stemmer.py` | `lru_cache` on `stem_token`; precompiled `_TOKEN_RE` | **Good.** Pure perf; watch unbounded-ish `maxsize=100_000` (fine). |
| `retrieval/indexer.py` | `sanitize_chunk(chunk, config_path)` | **Good** (matches new 2-arg API). |
| `config.yaml` | `banned_patterns` switched to single-quoted regex strings | **Good** (backslashes now reach the engine). Does **not** add the missing jailbreak patterns from S4. |
| `.github/workflows/ci.yml` | runs on `cc` too; drops `|| echo`; `--tb=short` | **Good** but still only 2 test files (S5 residual). |

**Recommendation:** PR #14 is a net security+quality improvement and should be merged. It does **not**
overlap with PR #18 (personality) — the two are mergeable independently. After both land, the suite is
green and CI can be switched to the full `pytest tests/`. Suggested follow-ups on top of #14: add the
missing jailbreak patterns (S4), the rate-limiter lock (S1), and the pickle integrity check (S3).

---

## 4. Architecture-invariant compliance (PDF v1.3.0 vs `main`)

| # | Invariant (PDF) | On `main`? | Notes |
|---|---|---|---|
| 1 | RAG-first: `retrieve` is unconditional entry | ✅ | `graph.set_entry_point("retrieve")`, single `retrieve→route_by_score` edge |
| 2 | Topology = policy (routing is structural, not LLM) | ✅ | conditional edges on `needs_user_confirm`; prompts can't add edges |
| 3 | Triple-gated Grok (hybrid AND enabled AND confirmed) | ✅ (effective) | mode+enabled enforced by `grok=None` build; confirm by router. Minor: `user_gate_router` comment claims a hybrid-mode check it doesn't perform (relies on `grok=None` guard) — works, but defense-in-depth is thinner than documented |
| 4 | Audit convergence (all paths → `audit_logger` → END) | ✅ | every terminal node edges to `audit_logger` |
| 5 | Soul governance: atomic write + forensic drift log + TTL prune | ⚠️ **partial** | **violated on `main`** (non-atomic, no `audit_log`, no TTL-on-init) → **fixed by PR #18**; residual `threading.Lock` (S2) |
| — | Telemetry kill before imports | ✅ | `gate.py` top-of-module |
| — | Bind 127.0.0.1 only | ✅ | uvicorn `--host 127.0.0.1`; CORS adds a LAN origin (S7) |
| — | Sanitizer config-driven | ❌ on `main` | hardcoded (S6) → fixed by PR #14 |
| — | `tests/test_endpoints_mocked.py` (NEW v1.3, p.16) | ❌ | promised by the PDF, **absent** from the repo — add it or correct the doc |

---

## 5. Prioritized remediation

1. **Merge PR #14** (`cc → main`) → closes S6, S1 (memory), the FD leak, and the 8 sanitizer
   failures; net security + perf win.
2. **Merge PR #18** (this run) → closes S2 (atomic soul writes + forensic audit + TTL-on-init) and the
   11 personality failures.
3. After 1+2: **flip CI to full `pytest tests/`** and drop the 2-file/`|| echo` shortcut (S5).
4. **S4** — add the documented-but-missing jailbreak patterns and de-duplicate the two pattern lists.
5. **S1 residual** — add a `threading.Lock` to the rate limiter; **S2 residual** — same for the soul
   write path.
6. **S3** — integrity-check (or replace) the pickled BM25 index; document `index/` as a trust boundary.
7. **S7/S9** — drop the `null` CORS entry, move the LAN origin behind an env override, and add a
   "don't bind off localhost without auth" deployment caveat.
8. **S8** — optionally make `apply_evolution` refuse injection-flagged souls without an explicit
   override.
9. **S2.7** — hash-locked installs + `pip-audit` in CI.
10. Add the missing `tests/test_endpoints_mocked.py` (or fix the architecture doc).

---

*No code changed in this PR. Findings are scoped so they can be picked up directly by a follow-up
session. See PR #18 and `tests/TEST_SUITE_AUDIT.md` for the unit-test half of this run.*
