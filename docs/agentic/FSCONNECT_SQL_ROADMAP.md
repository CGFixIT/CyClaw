# CyClaw Connectors — Staged Roadmap (`fsconnect` / `sqlconnect` and beyond)

> Status: **v0.1 shipped** — `agentic/fsconnect/` (scoped reads + gated, confined
> writes + toggleable corpus indexing) and `agentic/sqlconnect/` (read-only SQL
> scaffold, disabled). Both are out-of-band, opt-in, and disabled by default. This
> document is the forward plan for deferred and additional capabilities. Every item
> below stays **governed, gated, audited, and out-of-band** (never imported by
> `gate.py` / `graph.py` / `mcp_hybrid_server.py`).

## Design invariants every phase must hold

- **Out-of-band isolation.** New code lives under `agentic/<connector>/` and is run
  only via `python -m agentic.<connector>.cli`. The both-direction AST guard in
  `tests/test_agentic_isolation.py` (recursive) must keep passing.
- **Topology = policy.** No connector becomes a LangGraph node or LLM caller.
- **pathsafe is the only filesystem authority.** Reads and writes both validate
  through `agentic/fsconnect/pathsafe.py`; never reintroduce string-based path checks.
- **Gated mutation.** Any new write/mutating capability reuses the four-gate pattern
  (`enabled` + explicit flag + human `reason` + `confirm`) and audits every action.
- **Compliance-as-features.** Each capability maps to a control (NIST 800-171 / CMMC /
  HIPAA / SOC 2) that becomes a selling point.

---

## Filesystem connector — next phases

### FS Phase 2 — production write-enablement
- Operator playbook + security review checklist for flipping `writes_enabled: true`.
- `fs_delete` behind the destructive gate (`--confirm` + `--reason`), with a
  trash/soft-delete option instead of unlink.
- Quotas per writable root; write rate-limiting reusing `utils/ratelimit.py`.

### FS Phase 3 — incremental indexing & richer corpus
- Watch-based incremental reindex (`inotify` on Linux / `ReadDirectoryChangesW` on
  Windows) instead of full restage; content de-duplication by sha256.
- Local OCR for scanned PDFs/images (Tesseract, fully offline) before ingestion.
- **Quarantine of injection-flagged content**: today the indexer flags
  OWASP∪banned-pattern hits advisorily; Phase 3 routes flagged files to a quarantine
  area and requires human release before they enter the corpus.

### FS Phase 4 — Windows hardening (already designed, needs a Windows CI lane)
- Wire `GetFinalPathNameByHandle` re-assertion on the open handle into the Windows
  branch of `pathsafe` and add a Windows CI runner so the `# pragma: no cover`
  branches are exercised (junction/UNC/8.3/ADS fixtures).
- Per-root NTFS ACL inspection surfaced in `fs_stat` (advisory least-privilege check).

### Audit hardening (connector-wide, high buyer value)
- **Hash-chain / append-only tamper-evident audit** — the regulated-buyer RFP
  disqualifier. Chain each `audit.jsonl` record to the prior record's hash and store
  the head where deployer access cannot rewrite history.
- Add a plain-language **"rule applied"** field to each audited action (the human-
  readable reason an op was allowed/denied) for auditor reconstructability.

---

## SQL connector — next phases

### SQL Phase 2 — usability behind the read-only guard
- Live-DB integration tests (Postgres + MSSQL) in a dedicated CI service container so
  the `# pragma: no cover` connect/execute paths are exercised.
- Schema-aware **NL→SQL** helper (operator-driven, content-agnostic): a generated
  query still passes `assert_read_only_sql` before execution — generation never
  bypasses the guard.
- More dialects (MySQL/MariaDB, Oracle, SQLite); per-query cost caps and EXPLAIN
  pre-checks; row-level PII redaction reusing `policy.privacy`.

---

## OS-level agentic integration (Windows & Linux) — deferred, low-risk first

> Staged from lowest to highest risk. All read-first, allow-listed, dry-run-default,
> with any mutation behind the four-gate pattern and a hard **no-egress** rule.

1. **(seeded in v0.1)** `agentic.fsconnect.cli reveal` — open a writable root in the
   OS file manager (`explorer` / `open` / `xdg-open`; argv-list, out-of-band,
   operator-run). Already shipped as `agentic/fsconnect/osutil.py`.
2. **terminal.html "Open file share" button** — *deferred.* Requires a request-path
   endpoint in `gate.py`, which touches the loopback API surface and therefore gets
   its own isolation + security review before implementation. Sketched here, not built.
3. **Read-only system inventory** — process/service listing (`tasklist` / `ps`,
   `Get-Service` / `systemctl`), scheduled-task inventory (`schtasks` / cron /
   systemd timers), Windows registry **read**, event-log / journald tailing. Each is
   a new allow-listed, argv-list, audited op in an `agentic/osconnect/` package
   mirroring the connector recipe; read-only first.
4. **Governed OS actions** (later, high-risk) — start/stop a service, run an
   allow-listed maintenance script: only behind the four-gate pattern, confined to an
   operator-curated allow-list, dry-run by default, fully audited, never via the shell.

---

## Other connectors worth building for this ICP

- **On-prem IMAP / Exchange (EWS), retrieval-only** — surfaces mailbox content
  without a cloud Graph proxy; "send" stays out of scope / behind a future gate.
- **On-prem SIEM (Splunk / Elastic), read-only** — defense/CMMC log retrieval.
- **Direct SMB/CIFS share** — when the share is not mountable locally, a read-only
  SMB client mirroring the fsconnect op-allow-list shape.

## When to extract a shared base

Once `fsconnect` + `sqlconnect` are joined by a third connector (likely IMAP or a
direct-SMB client), extract a `connectors/base.py` ABC capturing the shared shape
(disabled-default config, op allow-list, audit, four-gate mutation, selftest, CLI
exit-code contract). Do **not** refactor the existing `agentic/`/`sync/` modules into
it; the base is for *new* connectors.
