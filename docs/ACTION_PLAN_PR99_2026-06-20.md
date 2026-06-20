# Action Plan — Remediating PR #99 ("6.20.26-Review")

**Status:** living document · **Date:** 2026-06-20 · **Owner:** maintainer-gated
**Source review:** PR #99 → `docs/REVIEW_2026-06-20.md` (13 verified findings)
**This PR implements:** Findings **#8, #9, #11** (low-risk, no behavior change). Everything
else is assessed, root-caused, and given a ready-to-apply plan below with an explicit
sequencing/risk rationale for why it is *not* bundled here.

---

## 1. Purpose & method

PR #99 is a review document, not a fix. This plan turns its 13 findings into an
executable remediation roadmap. For every finding we record:

1. **Assess** — is it real, what is the blast radius, what severity?
2. **Analyze** — root cause (not just symptom).
3. **Plan** — concrete fix (diff-level), test, and rollout/migration cost.
4. **Implement** — done here only when the fix is small, behavior-preserving, and
   covered (or coverable) without a product decision or index migration.

**Guiding constraint:** CyClaw's CI runs an explicit hermetic suite plus a real
ChromaDB+BM25 RAG smoke. Any change that alters retrieval scores, routing, or
auth posture can flip CI and/or an existing test that *documents intended
behavior*. Those changes are deliberately staged into their own PRs with the
test updates and validation they require — they are not safe to slip into a
"review-cleanup" PR.

---

## 2. Disposition at a glance

| # | Sev | Finding | Disposition |
|---|-----|---------|-------------|
| 1 | HIGH | Chroma L2/cosine metric mismatch corrupts scores | **Plan — Phase 1** (needs reindex + gate re-validation) |
| 2 | HIGH | Soul scanner (13) weaker than query scanner (31) | **Plan — Phase 2** |
| 3 | MED | No `TrustedHostMiddleware` (DNS-rebinding) | **Plan — Phase 3** |
| 4 | MED | `require_api_key` no-op in open mode | **Plan — Phase 3** (product decision + test update) |
| 5 | MED | `user_gate_router` escalates to Grok regardless of mode | **Plan — Phase 3** |
| 6 | MED | Single-path fallback uses non-RRF scores vs `min_score` | **Plan — Phase 1** (coupled to #1) |
| 7 | LOW/MED | `restore_from_backup` passes `scan=False` | **Re-assess — downgrade** (a naive flip breaks an intentional test) |
| 8 | LOW | `CYCLAW_API_KEY` missing from `_sanitize_error` redaction | ✅ **Implemented here** |
| 9 | LOW | Unescaped `meta` values in `innerHTML` (latent XSS) | ✅ **Implemented here** |
| 10 | LOW | Audit redaction two-tier; retrieval errors bypass secret patterns | **Plan — Phase 4** |
| 11 | LOW | SQLite SELECTs outside `self._lock` | ✅ **Implemented here** |
| 12 | LOW | MCP `_handle_search` skips `check_input` (by-design) | **Decision — document; optional defense-in-depth** |
| 13 | LOW | `config.yaml:175` curly-quote `null` CORS entry | **No action** (per maintainer direction; dead/harmless) |

---

## 3. Implemented in this PR (Phase 0 — safe, behavior-preserving)

### #8 — Redact `CYCLAW_API_KEY` in `_sanitize_error` (`gate.py`)
- **Root cause:** the live-env redaction loop listed `GROK_API_KEY`,
  `LANGCHAIN_API_KEY`, `LANGSMITH_API_KEY`, `SSC_TOKEN` — but not the server's
  *own* bearer secret. An exception raised on the auth path (or any handler that
  has the key in scope) could echo it into the HTTP 500 body.
- **Fix:** add `"CYCLAW_API_KEY"` to the tuple. One line; no test asserts the
  tuple contents, so no churn.
- **Verify:** `_sanitize_error(Exception("leak <key>"))` → `[REDACTED]` when the
  env var is set and longer than 8 chars.

### #9 — Escape interpolated values in `addEntry` (`static/terminal.html`)
- **Root cause:** `addEntry()` builds an HTML string and assigns it to
  `innerHTML`. The `meta` key/value and the `label` were interpolated raw. The
  page already ships an `escHtml()` helper used for the answer body but not here.
- **Fix:** route `label`, `m.k`, `m.v` through `escHtml()`. Frontend-only;
  values are coerced to string by `textContent` inside the helper.
- **Verify:** a meta value of `<img src=x onerror=alert(1)>` renders as text.

### #11 — SQLite reads under the write lock (`utils/personality.py`)
- **Root cause:** the connection is opened with `check_same_thread=False` and
  shared across FastAPI threadpool workers. Writes were serialized by
  `self._lock`, but the two SELECTs (`_load_soul` latest-hash check, and
  `get_version`'s `MAX(id)`) read outside it, so a read could race a concurrent
  `INSERT`+`commit`.
- **Fix:** wrap both SELECTs in `with self._lock:`. Confirmed **no re-entrant
  nesting**: `apply_evolution` calls `get_version()` only *after* releasing its
  write-lock block, and `_load_soul`'s read precedes (does not nest inside) its
  write blocks. `threading.Lock` is non-reentrant, so this matters — verified.
- **Verify:** existing `test_personality.py` / `test_personality_changes.py`
  (version + drift assertions) still pass; behavior is unchanged single-threaded.

---

## 4. Phase 1 — Retrieval correctness (#1 + #6, coupled)

These two are one problem viewed from two angles and must land together with a
reindex and a score-gate re-validation.

### #1 — Chroma distance metric
- **Assess (HIGH):** `create_collection` is built with the **default `l2`**
  space. Query/index embeddings *are* L2-normalized (`embeddings.py`,
  `normalize_embeddings=True`), so vectors are unit length. For unit vectors
  Chroma's squared-L2 distance ranges `0…4`, and `hybrid_search.py:96` computes
  `score = 1 - distance` → a **−3…+1** range that is *not* cosine similarity.
- **Analyze:** the *fused* path is partly insulated — `route_by_score` gates on
  the RRF `top_score` (rank-based, `Σ 1/(rrf_k+rank)`), not the raw semantic
  score. The corruption bites hardest on (a) the **semantic-only fallback**
  (see #6), where the raw score *is* compared to `min_score`, and (b) every
  `semantic_score` surfaced in the API/UI/audit.
- **Plan:**
  ```python
  # retrieval/indexer.py — create_collection
  collection = client.create_collection(
      collection_name,
      metadata={"hnsw:space": "cosine"},
  )
  ```
  Then **rebuild the index** (`python -m retrieval.indexer`). With cosine,
  `distance = 1 - cos` (range `0…2`) and `score = 1 - distance = cos`.
- **Migration / CI:** the CI `Real RAG Query Smoke` rebuilds the index every run,
  so cosine takes effect there automatically — but the smoke and `min_score`
  (0.028) must be re-checked against the new score distribution before merge.
- **Risk:** medium — changes every semantic score; requires the Phase-1 gate
  re-tune. Do **not** ship without rebuilding + confirming the smoke passes.

### #6 — Single-path fallback scoring vs `min_score`
- **Assess (MED):** when one retrieval path is empty, `hybrid_search` returns the
  surviving path's **raw** scores (semantic `1−distance`, or BM25 — which can be
  ≫ 1), never RRF. `route_by_score` then compares that raw `top_score` to a
  `min_score` (0.028) that was tuned for RRF magnitudes, so degraded retrieval
  almost always reads as "high confidence".
- **Plan:** in the single-path branches, either (a) recompute an RRF-style score
  so the gate sees a comparable scale, or (b) carry a per-mode threshold. Land
  with #1 so the gate is validated once against final score semantics.
- **Test:** extend `test_hybrid_search.py` with a semantic-empty and a
  keyword-empty case asserting the gate behaves sanely.

---

## 5. Phase 2 — Injection-defense parity (#2; revisits #7, #12)

### #2 — Unify the soul scanner with the 31-pattern query filter
- **Assess (HIGH):** `personality.OWASP_INJECTION_PATTERNS` is a hardcoded
  13-pattern list. The query path uses the **31** curated patterns in
  `config.yaml` (`policy.prompt_filter.banned_patterns`), including the entire
  *Memory/Persistence* sub-category explicitly labelled "HIGH PRIORITY for RAG +
  soul". None of those are in the soul scanner — so a proposal containing
  `update your soul` / `core instruction, never forget` passes
  `apply_evolution` and is prepended to **every** LLM system prompt.
- **Analyze:** two independently-maintained pattern lists guarantee drift; the
  weaker one guards the higher-value asset (the soul).
- **Plan:** have `_scan_injection` compile + reuse the config `banned_patterns`
  (the same set `utils/sanitizer._load_filter` already compiles), unioned with
  the existing OWASP list so nothing is lost. Keep the method signature; only the
  pattern source changes.
- **Test:** add cases to `test_personality.py` / `test_personality_changes.py`
  asserting each memory/persistence pattern is flagged by `propose_evolution`
  and blocked by `apply_evolution`.
- **Risk:** low-medium — could newly reject a soul that embeds a banned phrase;
  that is the intended tightening, but worth a changelog note.

### #7 — `restore_from_backup(scan=False)` — **re-assess, do not blind-flip**
- **Finding says:** a previously-admitted poisoned soul could be reinstated
  without a check.
- **Counter-evidence:** `test_personality.py::test_scan_false_bypass_for_trusted_restore`
  **explicitly asserts** that `apply_evolution(..., scan=False)` must *not* raise —
  `scan=False` is a documented, intentional escape hatch for the trusted restore
  path. The `.bak` is only ever written from `self.soul_core`, i.e. content that
  already passed the scan on its way in.
- **Plan:** instead of flipping to `scan=True` (which would break that test and
  the documented contract), add a **non-blocking re-scan that audit-logs** any
  match on restore (observability without changing the trust model), and once #2
  lands, reconsider whether restore should hard-fail. Treat as **LOW**.

### #12 — MCP `_handle_search` skips `check_input` — **document the decision**
- The MCP server is retrieval-only (`sampling = None`) and serves a trusted local
  stdio caller; #99 itself marks this "by-design". **Plan:** add a short
  docstring note making the decision explicit, and optionally add `check_input`
  as cheap defense-in-depth (it only raises on banned patterns / over-length).
  Low priority; no functional gap today.

---

## 6. Phase 3 — Network & auth hardening (#3, #4, #5 — behavior changes)

> These alter security posture and/or routing and need their own PRs, product
> decisions, and test updates. Grouped because they interact.

### #3 — `TrustedHostMiddleware`
- **Plan:**
  ```python
  from starlette.middleware.trustedhost import TrustedHostMiddleware
  app.add_middleware(TrustedHostMiddleware, allowed_hosts=[...])  # before CORS
  ```
- **Caveat:** the allow-list must include the **LAN host `10.0.0.112`** (and
  `127.0.0.1`, `localhost`) or the existing home-lab browser client breaks.
  Source the list from config so it stays in sync with `allowed_origins`. Host
  matching ignores port, so no port entries are needed.

### #4 — Open-mode auth no-op
- **Assess:** when `CYCLAW_API_KEY` is unset, `require_api_key` returns early and
  all `/soul/*` mutation endpoints are unauthenticated.
- **Tension:** `test_security.py::test_auth_disabled_when_no_env_var` asserts the
  current open-mode behavior. Any fix is a **product decision** (fail-closed vs.
  auto-generate a one-time startup token printed to the log) and requires
  updating that test. **Plan:** recommend auto-generating a random token at
  startup when none is set, logging it once; pair with #3 so a rebind attacker
  still can't reach the host.

### #5 — `user_gate_router` ignores app mode
- **Assess:** the router branches only on `user_confirmed_online`, never on
  `cfg["app"]["mode"]`. In **offline** mode the low-score path still *asks* the
  user to confirm "send to Grok?", but `grok` is `None`, so `grok_fallback_node`
  just returns the offline placeholder — the confirm prompt is a dead-end.
- **Plan:** in offline mode, skip the confirm gate and route low-score queries
  straight to `offline_best_effort`. The router has no `cfg`; inject `mode` into
  `GraphState` at `route_by_score`/`user_gate`, or branch in `user_gate_node`.
  Update `test_graph.py` routing assertions.

---

## 7. Phase 4 — Audit hygiene (#10)

### #10 — Two-tier redaction lets retrieval errors bypass secret patterns
- **Assess:** `hybrid_search` audits degraded paths with
  `audit_log({"event": "retrieval_degraded", "error": str(e)})`. `audit_log`
  redacts via `redact_sensitive` (emails/IPs + `redact_secrets_like`) but **not**
  the richer `gate._SECRET_PATTERNS` (Bearer tokens, `api_key=…`, `sk-…`,
  `ghp_…`). A retrieval error string carrying a bearer token would land in
  `audit.jsonl` un-redacted.
- **Plan:** consolidate to one redaction surface — either route audit error
  strings through the same pattern set as `_sanitize_error`, or fold those
  patterns into `config.policy.privacy.redact_secrets_like` so `audit_log` covers
  them centrally. Prefer the config route (single source of truth).

---

## 8. No-action / documented (#13)

`config.yaml:175` uses a **curly-quoted** `“null”` in `allowed_origins`. Per
maintainer direction this is left as-is: Starlette's `CORSMiddleware` never
matches it (it is not a real origin and not the ASCII string `"null"`), so it is
inert. Flagged here only for completeness; **no change**.

---

## 9. Recommended merge order

1. **Phase 0 (this PR)** — #8, #9, #11. No behavior change; safe to merge now.
2. **Phase 1** — #1 + #6 together, *with reindex + smoke re-validation*.
3. **Phase 2** — #2 (scanner unification) + tests; then revisit #7/#12.
4. **Phase 3** — #3, then #5, then #4 (#4 last — it carries the product decision).
5. **Phase 4** — #10 redaction consolidation.

## 10. Verification checklist

```bash
# Phase 0 (this PR)
GROK_API_KEY=dummy pytest tests/test_personality.py tests/test_personality_changes.py \
                          tests/test_security.py tests/test_gate.py -q --tb=short
python -m py_compile gate.py utils/personality.py     # syntax gate
# manual: open the Soul Console, confirm a meta value with markup renders as text

# Phase 1 (when undertaken)
python -m retrieval.indexer && python -m tests.ci_rag_smoke   # cosine + gate re-check
```
