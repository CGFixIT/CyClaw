# Feature 3 — LangGraph per-node execution trace (local-first observability)

> **Status:** planning only. No code written. Anchors verified against current `main`.
> **Build order:** second (see `README.md`). Rides Feature 1's hashing for free.

---

## 1. Problem & buyer need

When a compliance officer asks *"why did this query escalate to the external Grok API instead of
answering locally?"*, or an operator asks *"which node took 8 of the 9 seconds?"*, today's audit event
cannot answer. The `audit_logger_node` event (`graph.py:509-528`) records the **outcome**
(`model_used`, `top_score`, `online_escalated`) but not the **reasoning trace** — no per-node timing, and
no record of *why* `user_gate_router` chose `grok_fallback` over `offline_best_effort` (was
`confirmed=True`? was `grok` unavailable?). PR #388 only added two `logger.debug` lines around
context-budget math in `_context_char_budget` / `_format_context_chunks` — there is **no** structured,
persisted per-node trace today. Auditors (reconstructability) and operators (debugging) both need this;
2026 governance guidance explicitly calls for every autonomous action to be logged and *defensible*.

---

## 2. Design decision: a `trace` field on `GraphState`, one tiny helper — no Tracer/Span class

`graph.py` has 7 node functions (`retrieve_node`, `route_by_score_node`, `local_llm_node`,
`user_gate_node`, `grok_fallback_node`, `offline_best_effort_node`, `audit_logger_node`) plus 2 router
functions (`score_router`, `user_gate_router`, `graph.py:558,564`) that decide edges but return no state.

Per ponytail's "3 similar call sites beats a premature helper, 4+ may justify a tiny one": 7 timing call
sites crosses that threshold, so **one ~5-line helper** is justified — but a full `Tracer`/`Span` class
is **not**, because the nodes are flat and sequential (no nesting) and there is exactly one sink (the
audit event), per the offline-first constraint. The dict-shape-drift failure mode that `graph.py`'s own
header comment warns about (formatting logic that got copy-pasted across the response paths and drifted)
is exactly what the single helper prevents.

---

## 3. Files touched

### `graph.py`

- Add `import time` and `import operator` (and `from typing import Annotated`) at the top.
- Extend `GraphState` (`graph.py:75-97`) with: `trace: Annotated[list[dict], operator.add]`. The
  **reducer** (`operator.add`) is the LangGraph-idiomatic mechanism so each of the 6 executing nodes can
  *append* its entry without clobbering siblings — LangGraph's default per-key merge is "last write
  wins", which would lose all but the last node's entry. This is a one-line declaration, not a new
  abstraction, and removes any hand-rolled read-modify-write race. Add a one-line comment at the field
  declaration stating the **topology=policy guarantee** (the list is write-only until `audit_logger_node`;
  no routing function ever reads it), matching the existing inline-rationale comment style in `graph.py`.
- Add helper near `_context_char_budget` (`graph.py:142`):
  `_record_node_timing(node: str, start: float, **extra) -> dict` → returns
  `{"node": node, "duration_ms": round((time.monotonic() - start) * 1000, 2), **extra}`.
- Each of the 7 nodes: capture `start = time.monotonic()` at entry and add a single-element
  `"trace": [_record_node_timing(...)]` to its existing return dict (the reducer concatenates across
  nodes), **only when** `cfg.get("logging", {}).get("trace_enabled", False)` — when disabled the node
  skips the `time.monotonic()` call entirely and returns no `trace` key, so the feature has genuinely
  zero overhead when off, not merely zero *persisted* overhead. Per-node `extra`:
  - `retrieve_node` → `{"hit_count": …, "top_score": …, "retrieval_mode": …}`
  - `route_by_score_node` → `{"score": top_score, "threshold": threshold, "decision": "local_llm"|"user_gate"}`
    — this is the human-readable **"rule applied"** field `FSCONNECT_SQL_ROADMAP.md:51` asked for,
    satisfied here rather than separately invented.
  - `local_llm_node` → `{"model": "local", "error": error}`
  - `user_gate_node` → `{"confirmed": confirmed}`
  - `grok_fallback_node` → `{"model": "grok", "gate_reason": …, "error": error}`
  - `offline_best_effort_node` → `{"model": "offline-best-effort", "gate_reason": …, "error": error}`
- The two **router** functions are not nodes and return no state, so they cannot append trace entries.
  Capture their rationale at the *next executing node* instead: `grok_fallback_node` and
  `offline_best_effort_node` read `state.get("user_confirmed_online")` (and, for grok, whether `grok` was
  `None` / `is_available()` was the deciding factor) into their `gate_reason` extra. This captures the
  triple-gate "why" **without touching the router signatures** (which are directly unit-tested in
  `tests/test_graph.py`).
- Modify `audit_logger_node` (`graph.py:500-552`): it is the terminal node, so it must include **its
  own** trace entry, which the `operator.add` reducer cannot supply in time — a `trace` entry the node
  *returns* is merged into state only *after* the node returns, i.e. after `event` is already built and
  `audit_log()` already called. Build a **local** list inside the node:
  `full_trace = state.get("trace", []) + ([_record_node_timing("audit_logger", start)] if trace_enabled else [])`,
  then set `"trace": full_trace` on the `event` dict (after `"error"` at `:528`). (Returning the same
  single-element entry under `"trace"` for the reducer is optional/harmless since nothing downstream of
  the terminal node reads merged state, but include `event`'s copy so the persisted record is complete.)
  This way the trace rides into `audit_log()` and — when Feature 1 is enabled — gets hash-chained
  automatically with everything else. **Zero Feature-1-specific code here.**

**Invariant safety (state explicitly in the doc):**
- *Topology = policy holds.* Every trace entry is written *after* the node's routing-relevant fields are
  already computed and returned; `score_router`/`user_gate_router` bodies, signatures, and reads are
  unchanged; the `trace` list is never consulted by any routing function.
- *Telemetry-kill posture holds.* This is `time.monotonic()` deltas into a Python dict flowing into the
  *same* local `audit_log()` write that already exists — no OTel SDK, no external exporter, no new I/O
  sink, no network call. (`gate.py:37-64` kills OTel/telemetry env vars at import; this feature adds none.)

### `config.yaml`

```yaml
logging:
  trace_enabled: false   # opt-in per-node execution trace (timing + routing rationale); local-only, no external exporter
```

**Default `false`** for consistency with Feature 1 — both touch the audit-record shape, and an operator
should opt into a record-shape change knowingly. The two flags are independent: enable `trace_enabled`
for observability and/or `hash_chain_enabled` for tamper-evidence as needs dictate.

### `static/terminal.html` — explicit stretch goal, DEFERRED (not in v1)

A read-only "recent traces" panel reusing the existing Soul/Sync/Agentic panel pattern would need a new
`GET /audit/recent?n=N` endpoint. That endpoint returns near-raw per-query trace data — a **different
exposure profile** than the aggregates-only `/audit/summary` — and deserves its own security review
before shipping, exactly as `FSCONNECT_SQL_ROADMAP.md:78-79` defers the terminal "Open file share"
button. **Recommendation: defer the endpoint and the UI entirely; v1 ships trace-in-audit-log only.**

---

## 4. New / changed signatures

- `graph.py`: new `GraphState` field `trace: Annotated[list[dict], operator.add]`; new helper
  `_record_node_timing(node: str, start: float, **extra) -> dict`. All 7 node function **signatures
  unchanged** — only their return-dict bodies gain a conditional `"trace"` key.

---

## 5. Tests

- Extend `tests/test_graph.py` with `class TestExecutionTrace`:
  `test_trace_disabled_by_default_no_trace_field`,
  `test_trace_enabled_records_all_executed_nodes_in_order` (high-score run → trace is
  `["retrieve","route_by_score","local_llm","audit_logger"]` in order),
  `test_trace_records_route_decision_and_score`,
  `test_trace_records_grok_gate_reason_on_confirmed_path`,
  `test_trace_records_offline_reason_on_declined_path`,
  `test_trace_duration_ms_is_nonnegative_number`, and the explicit topology=policy regression guard
  `test_trace_does_not_influence_routing` (two runs, identical inputs, `trace_enabled` flipped → identical
  `answer_model`/routing outcomes).
- One bridging case in `tests/test_audit_chain.py` (Feature 1's file): a chained **and** traced event
  still verifies via `verify_chain()` — proves the two features compose.

---

## 6. Sequencing & integration

**Land after Feature 1** (or alongside). Feature 3's `trace` field is added to the same event dict
Feature 1 hashes; because Feature 1's `_canonical_json`/hashing operates on whatever dict it receives
(schema-agnostic), adding `trace` later requires **zero** changes to Feature 1's code. If Feature 3 lands
first with chaining disabled, nothing breaks. The bridging test above closes the loop.

---

## 7. Verification commands

```bash
cd /home/user/CyClaw
GROK_API_KEY=dummy python -m pytest tests/test_graph.py -v -k "Trace or trace"
GROK_API_KEY=dummy python -m pytest tests/test_graph.py tests/test_audit.py tests/test_audit_chain.py -v
GROK_API_KEY=dummy python -m pytest tests/ -q --cov=graph --cov-report=term-missing
ruff check graph.py ; mypy graph.py
# Manual: enable trace_enabled, run one /query (e.g. via run-cyclaw skill), then inspect the last record:
tail -1 logs/audit.jsonl | python -m json.tool
```

---

## 8. Ponytail self-check

- **YAGNI** — no `Tracer`/`Span` class for 7 flat, non-nested call sites; no live OTel SDK / pluggable
  exporter (forbidden as default and no concrete need identified). One helper + one reducer field.
- **stdlib-first** — `time.monotonic()`, `operator.add`, dict literals; zero new dependencies. Trace
  storage **reuses** the existing `audit_log()` write path — it does **not** create the competing,
  parallel, unchained log stream the design explicitly warns against.
- **Minimal abstraction** — exactly one ~5-line helper at the "4+ call sites" threshold, plus a one-line
  LangGraph-idiomatic reducer; no class hierarchy.
- **No half-measures** — the routing "why" (triple-gate rationale) is genuinely captured via
  `gate_reason` on the escalation nodes, not punted on because routers return no state.
