# PR #99 Backlog — Phase 4 Implementation Plan: Audit Redaction Consolidation

> **Scope:** Finding **#10** (two-tier redaction: retrieval errors written to the audit log
> bypass the richer `_sanitize_error` secret patterns).
> **Parent:** `docs/ACTION_PLAN_PR99_2026-06-20.md` (PR #106); findings in PR #99.
> **Related (already shipped):** Finding **#8** (`CYCLAW_API_KEY` added to `_sanitize_error`)
> landed in PR #106 — this phase generalizes that one-off into a single redaction surface.
>
> **This document is a plan, not the implementation.**

---

## 0. TL;DR

There are **two** redaction code paths with **different** coverage:
1. `gate._sanitize_error` — Bearer tokens, `api_key=…`, `sk-…`, `ghp_…`, Slack, AWS, plus
   live env-var values. Applied to **HTTP 500 bodies**.
2. `utils.logger.redact_sensitive` (via `audit_log`) — emails, IPs, and
   `policy.privacy.redact_secrets_like` (AWS/Slack/GitHub/`sk-` only). Applied to
   **audit-log string fields**.

Retrieval-degraded errors are audit-logged through path (2), so a secret that only path (1)
knows about (e.g. a `Bearer …` token or `api_key=…` form in an exception string) is written
to `audit.jsonl` **un-redacted**. Fix: make `redact_secrets_like` the single source of truth
and route both surfaces through it.

---

## 1. Finding #10 — Unify the two redaction surfaces

### 1.1 Problem statement
Sensitive material can be persisted to the append-only audit log because the audit redactor
covers fewer secret shapes than the HTTP redactor.

### 1.2 Evidence (current code on `main`)
- `retrieval/hybrid_search.py:138,142` — degraded paths:
  ```python
  audit_log({"event": "retrieval_degraded", "path": "semantic", "error": str(e)})
  ...
  audit_log({"event": "retrieval_degraded", "path": "keyword",  "error": str(e)})
  ```
- `utils/logger.py:93-104` — `redact_sensitive` applies only emails, IPs, and
  `policy.privacy.redact_secrets_like`.
- `config.yaml:149-153` — `redact_secrets_like` = AWS, Slack, GitHub PAT, `sk-…` **only**.
  Missing vs. `gate._SECRET_PATTERNS`: **`Bearer …`** and the generic **`api_key[:=]…`**
  form.
- `gate.py:105-124` — `_sanitize_error` has the richer pattern set + live-env redaction.

### 1.3 Root-cause analysis
Two independently-grown redaction lists. The audit path (which writes to durable storage —
arguably the **more** important surface) has the **weaker** list. The `str(e)` of a
retrieval error can carry an upstream HTTP error string containing an `Authorization: Bearer`
header or an `api_key=` query param, which the audit redactor does not match.

### 1.4 Proposed fix — single source of truth (config-first)
**Preferred — widen `redact_secrets_like` and route everything through `redact_sensitive`:**
1. Add the two missing shapes to `config.yaml: policy.privacy.redact_secrets_like`:
   ```yaml
   redact_secrets_like:
     - "Bearer\\s+[A-Za-z0-9\\-_\\.]+"
     - "[Aa][Pp][Ii][_-]?[Kk][Ee][Yy][\"\\s:=]+[\\w\\-\\.]+"
     - "AKIA[0-9A-Z]{16}"
     - "xox[baprs]-[0-9a-zA-Z-]+"
     - "ghp_[a-zA-Z0-9]{36}"
     - "sk-[a-zA-Z0-9]{32,}"
   ```
   (`redact_sensitive` already compiles these via `_compiled_redactors`, cached, and skips
   invalid regex — so adding entries is safe and needs no code change there.)
2. Have `gate._sanitize_error` **also** call `redact_sensitive` (or build `_SECRET_PATTERNS`
   from the same config list) so the two surfaces cannot diverge again. Keep the live-env
   redaction loop (that is HTTP-response-specific and complements the config patterns).

**Alternative — pre-sanitize at the call site:** wrap the retrieval error string before
`audit_log`. Rejected as the primary fix: it patches one call site, not the class of bug.

### 1.5 Design decisions
- **DECISION (canonical home):** make `policy.privacy.redact_secrets_like` the single
  pattern list and derive both surfaces from it, **or** keep `_SECRET_PATTERNS` in code and
  have `redact_sensitive` import it. Prefer **config-first** — it is the documented privacy
  policy surface and is already plumbed through `_compiled_redactors`.
- **Ordering/escaping:** YAML single-vs-double quote escaping for the `Bearer`/`api_key`
  regexes must be verified (backslashes). Add a unit test that the compiled patterns match
  known samples so a quoting slip is caught.

### 1.6 Implementation steps
1. Extend `redact_secrets_like` in `config.yaml` with `Bearer` + `api_key` shapes.
2. Unify `gate._sanitize_error` to reuse `redact_sensitive` (keep live-env loop).
3. (Optional) Update `tests/conftest.py` `TEST_CONFIG` privacy list so tests exercise the
   widened set.
4. Confirm `mcp_hybrid_server` audit path (also uses `audit_log`) inherits the coverage —
   no separate change needed.

### 1.7 Test strategy
- `tests/test_audit.py`: add cases asserting that an audit event whose `error` field
  contains `Authorization: Bearer abc.def.ghi` and `api_key=SECRETVALUE` is written with
  those substrings **redacted**.
- Regression: existing email/IP/AWS redaction tests stay green.
- A `retrieval_degraded`-shaped event (semantic + keyword) round-trips through `audit_log`
  with secrets stripped.

### 1.8 Risk & rollback
- **Risk:** an over-broad `api_key` regex could over-redact benign audit text (e.g. the
  literal word "apikey" followed by punctuation). Keep the pattern anchored to a
  value-bearing form (`[:=]` or quotes) as in `gate._SECRET_PATTERNS`. **Rollback:** drop the
  two new config entries; behavior returns to the prior (weaker) set.

### 1.9 Acceptance criteria
- [ ] `Bearer` and `api_key=` shapes are redacted in audit-log string fields.
- [ ] HTTP and audit surfaces derive from one pattern source (no divergence).
- [ ] New `test_audit.py` cases pass; existing redaction tests unchanged.
- [ ] No measurable hot-path regression (`redact_sensitive` stays `lru_cache`-compiled).

---

## 2. Sequencing, dependencies, effort

| Step | Depends on | Est. |
|------|-----------|------|
| Widen `redact_secrets_like` (config) | — | 10 min |
| Unify `_sanitize_error` ↔ `redact_sensitive` | config | 25 min |
| Tests (`test_audit.py`) + conftest privacy | above | 30 min |

**Land order:** independent of Phases 1–3; can ship anytime. Small, low-risk — a good
"good first follow-up" after the #106 Phase-0 fixes. One PR.

## 3. Verification commands
```bash
GROK_API_KEY=dummy pytest tests/test_audit.py -q --tb=short
```

## 4. Out of scope (tracked elsewhere)
- Retrieval scoring (#1/#6) → Phase 1.
- Injection-defense parity (#2/#7/#12) → Phase 2.
- Network/auth posture (#3/#4/#5) → Phase 3.
- `config.yaml:175` curly-quote `null` origin (#13) → **no action** per maintainer direction.
