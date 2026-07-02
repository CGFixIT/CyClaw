# CyClaw Planning — Trust & Compliance Trio

This directory holds detailed, implementation-ready planning documents for three proposed
features that strengthen CyClaw's appeal to its stated ideal customer profile (regulated SMBs —
law firms, medical/dental, accounting) and to technical evaluators performing security due
diligence. Each doc is written so a future implementation session — or the maintainer — can
build the feature directly.

> **Status:** planning only. No production code has been written for these features. Each doc is
> pre-vetted against the five security invariants, the offline-first / telemetry-kill posture,
> ponytail / YAGNI discipline, and the 80% coverage target.

---

## Why these three

2026 market research converges on a single dominant blocker to agentic-AI adoption: buyers no
longer accept *claimed* security — they require **provable governance**. The buyer's question has
shifted from *"will the model be safe?"* to *"can we prove, auditably, that every AI action was
governed — and that our data stayed ours?"* That is the language of governance, compliance, and
data sovereignty, and it is the language these three features speak.

- **Shadow AI is the lived reality of the ICP.** 66% of office professionals have used AI tools at
  work they believed weren't permitted, and 89% first adopted AI *outside* work before bringing it
  in (Wakefield / PagerDuty 2026 shadow-AI surveys). For a law/medical/accounting firm, that means
  client data is already leaking into public models — CyClaw's offline-first, data-never-leaves
  posture is the direct answer, but only if its governance is **demonstrable**.
- 88% of organizations reported confirmed or suspected AI-agent security incidents in the past
  year, while 82% of executives *wrongly believe* their existing policies already protect them —
  a documented blind spot. Provable verification (Feature 2) closes it.
- Auditors and regulated-industry RFPs now demand **immutable, independently verifiable, and
  reconstructable** audit trails (SOC 2 Type II, HIPAA, state-bar record-retention rules) — exactly
  what Features 1 and 3 produce.
- **Memory poisoning** is the highest-severity unaddressed-by-most threat for this ICP: indirect
  injection that plants *persistent false beliefs* in an agent's memory (>95% injection success
  rate in 2026 research; arXiv 2601.05504 / MINJA; Lakera 2026). CyClaw **already** defends it (the
  `Memory/Persistence Manipulation` banned-pattern category in `config.yaml` + the enforced
  soul-mutation gate in `utils/personality.py`); Feature 2's payload corpus **proves** that defense
  holds on a live instance.

CyClaw's core differentiator is already *trust enforced by graph topology, not prompts*. These
three features turn that architecture into **evidence a buyer's own auditor can verify**:

| # | Feature | What it proves | Primary audience |
|---|---------|----------------|------------------|
| 1 | [Tamper-evident hash-chained audit log + evidence-pack export](01_tamper_evident_audit_log.md) | The audit trail was not silently altered or truncated | Auditors, compliance officers, insurers |
| 2 | [Customer-facing security/invariant verification suite](02_security_verification_suite.md) | The marketed security posture actually holds on *their* live instance | Buyer security teams, technical evaluators |
| 3 | [LangGraph per-node execution trace](03_graph_execution_trace.md) | *Why* each query routed as it did (incl. external-escalation rationale) | Auditors, operators, debuggers |

---

## What this deliberately does NOT duplicate

These features were chosen to **extend**, not re-propose, CyClaw's substantial existing roadmap.
The following are already planned/scoped elsewhere and are explicitly out of scope here:

- **TTL / retention / right-to-erasure purge** — `docs/PSYCLAW_FEATURE_IDEAS.md` item #2. (Feature 1
  notes a forward-compatibility constraint: a future purge must be chain-aware, but does not build it.)
- **Matter / client tagging + conflict wall** — `docs/PSYCLAW_FEATURE_IDEAS.md` item #3.
- **`invariant-guard` and `injection-redteam` dev skills** — `docs/PROPOSED_SKILLS.md`. Those are
  *development-time* tools (pre-merge CI diff check; iterative bypass discovery). Feature 2 is the
  distinct *post-deployment, customer-runnable, black-box* counterpart and cross-references both.
- **fsconnect / sqlconnect connector phases** — `docs/agentic/FSCONNECT_SQL_ROADMAP.md`. (Feature 1
  turns that doc's one-paragraph "hash-chain audit" *Audit hardening* stub into a real plan.)

---

## Recommended implementation order

**Feature 1 → Feature 3 → Feature 2.**

1. **Feature 1 first** — it is the riskiest piece (a hot-path concurrency lock, an atomic chain-head
   file, an external standalone verifier) and it establishes the **generic, schema-agnostic hashing**
   that Feature 3 then rides for free.
2. **Feature 3 second** — it only adds a `trace` field to the *same* `audit_logger_node` event dict
   that Feature 1 already hashes (`graph.py:509-528`), so no Feature-1 rework is needed. A bridging
   test confirms a chained + traced record still verifies.
3. **Feature 2 last** — by then the audit-record shape is stable (chained + traced), so its
   `check_audit_convergence` check asserts against the final shape and can later add a
   `chain_verified` assertion.

All three are independently shippable; this order minimizes rework, not coupling.

---

## Shared infrastructure (reused, not reinvented)

- **`metrics.compute_metrics` / `load_events`** (`metrics.py`) — the single audit-aggregation path.
  Feature 1's evidence pack and Feature 2's convergence check both reuse it; no third aggregator.
- **Atomic-write idiom** — `tmp` + `os.replace` from `utils/personality.py:308-315`. Feature 1's
  chain-head file reuses it verbatim.
- **Single convergence point** — `audit_logger_node` (`graph.py:500-552`) is the only place
  Features 1 and 3 integrate; security invariant #4 (audit convergence) guarantees there is exactly
  one such point, so no second wiring location exists.
- **Disabled-by-default config convention** — every new runtime behavior ships behind one boolean
  defaulting to `false`, matching `sync.enabled` / `agentic.enabled` / `guardrails.enabled` /
  `fsconnect.enabled` / `sqlconnect.enabled`. (Feature 2 has no such flag — it is an externally
  invoked tool, not a runtime behavior change.)
- **Console-script convention** — each feature adds at most one `[project.scripts]` entry
  (`pyproject.toml:50-55`): `cyclaw-audit-export` (F1), `cyclaw-verify` (F2), none (F3).
