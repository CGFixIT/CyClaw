# Feature 1 — Tamper-evident hash-chained audit log + compliance evidence-pack export

> **Status:** planning only. No code written. Anchors verified against current `main`.
> **Build order:** first (see `README.md`). Establishes the generic hashing Feature 3 reuses.

---

## 1. Problem & buyer need

`logs/audit.jsonl` is written today with a plain append — `open(log_path, "a").write(json.dumps(record) + "\n")`
(`utils/logger.py:148-149`). It carries **no integrity signal at all**: a line can be edited or deleted,
and a later reader has no way to tell. For CyClaw's regulated-SMB ICP this is a named **RFP
disqualifier**: `docs/agentic/FSCONNECT_SQL_ROADMAP.md:47-50` already calls out *"Hash-chain /
append-only tamper-evident audit … Chain each `audit.jsonl` record to the prior record's hash and store
the head where deployer access cannot rewrite history."* — but only as a one-paragraph stub. 2026
auditors (SOC 2 Type II, HIPAA, state-bar retention rules) require immutable, **independently
verifiable** trails. This feature makes the audit log cryptographically chained and ships a portable
"evidence pack" an external auditor can verify with **zero CyClaw install**.

> **Threat-model scope — state this plainly in the implementation and the evidence pack (do not
> overclaim).** A hash chain whose head lives *beside* the log only raises the bar; it does **not** make
> the log unforgeable against an attacker who controls the same filesystem, because that actor can
> rewrite the log, recompute every `record_hash`, and overwrite the head — `verify_chain` would then
> pass. Per `docs/THREAT_MODEL.md`, a **hostile local root / the operator themselves is explicitly
> out of scope** (trusted). The chain's real, honest value is therefore: (1) **export-time / external
> verification** — the auditor (or an append-only/WORM/external sink) records the chain head
> *independently* at a point in time, so any later in-place rewrite is detectable by comparing against
> that externally-held head; (2) detection of **partial or accidental** corruption/truncation (the
> `seq` counter + head-vs-last-line check); and (3) detection of tampering by any process that can write
> the log but **cannot also rewrite the head** (e.g. a compromised non-root subprocess, a backup/sync
> job). The design below supports (1) by making the head a small, separately-exportable artifact; an
> operator who needs protection against a local-root adversary must anchor the head in an external
> append-only store — documented as an option, not built, since that adversary is out of CyClaw's
> stated threat model.

This also satisfies the "signed PDF/CSV evidence pack" roadmap extension noted in
`docs/PSYCLAW_FEATURE_IDEAS.md` item #1 — where **"signed" is realized as the hash-chain proof**, not a
cryptographic PDF signature (no PDF dependency; see ponytail self-check).

In buyer/governance terms: this is the artifact a managing partner hands their auditor or malpractice
insurer to answer *"prove your AI's activity log wasn't altered"* — provable governance and data
sovereignty (the records never leave the operator's machine), not a claim.

---

## 2. Files touched

### `utils/logger.py` (core-path file — already owns `audit_log`)

Read the current `audit_log()` (`utils/logger.py:134-149`) carefully; the **ordering is the contract**:
it (a) takes a shallow copy `record = dict(event)` (never mutates the caller's dict, `:139`), (b) pops
`query` → `query_hash` (`:140-142`), (c) **recursively redacts** every non-skip field via `_redact_value`
(`:143-146`, skipping `_AUDIT_SKIP_KEYS = {"query_hash","timestamp","event"}` at `:110`), (d) stamps
`record["timestamp"]` (`:147`), then (e) appends one JSON line (`:148-149`).

Chaining must hook in **after step (d) and before step (e)** — i.e. hash the *fully-redacted,
fully-timestamped* record, the exact bytes that hit disk (so the external verifier reproduces the hash
from what it reads, and so no secret is ever hashed pre-redaction).

New helpers (all module-private):
- `_canonical_json(record: dict) -> str` — `json.dumps(record, sort_keys=True, separators=(",", ":"))`.
  This exact form (`sort_keys=True`, those separators) is the **contract the standalone verifier
  depends on**; document it in the docstring.
- `_chain_head_path(cfg: dict) -> Path` — reads new key `logging.audit_chain_head_file`, defaulting to
  a sibling of `audit_file` (`logs/audit_chain_head.json`). **Note (see §1 Threat-model scope):** a head
  co-located with the log does *not* defend against a same-filesystem actor who rewrites both — that
  adversary (hostile local root) is out of CyClaw's threat model. The default sibling location serves the
  in-scope value (export-time external verification + partial/accidental + non-root-subprocess tampering);
  the config key exists precisely so an operator who needs more can point it at an external/append-only
  store.
- `_read_chain_head(path: Path) -> str` — returns the stored `record_hash` of the last record, or the
  genesis sentinel `"0" * 64` if the head file is absent (first-ever record / post-rotation). A
  missing/corrupt head must be tolerated as genesis **with a warning**, never crash — a broken head file
  must not break the live `/query` path.
- `_write_chain_head(path: Path, record_hash: str, seq: int) -> None` — atomic write using the exact
  `tmp_path = path.with_suffix(path.suffix + ".tmp"); …write_text(…); os.replace(tmp_path, path)` idiom
  from `utils/personality.py:309,315`. Body: `{"record_hash": …, "seq": …, "updated": <iso8601>}`. The
  `seq` counter lets the exporter/verifier detect trailing-record truncation a pure walk would miss, and
  flags head/file desync.

Modify `audit_log()` — gated on a new config flag `logging.hash_chain_enabled` (read from `cfg`, already
loaded in the function):
- **Enabled:** `prev = _read_chain_head(head_path)`; `record["prev_hash"] = prev`;
  `record["record_hash"] = hashlib.sha256(_canonical_json({k: v for k, v in record.items() if k != "record_hash"}).encode()).hexdigest()`;
  append the line (existing write); then `_write_chain_head(head_path, record["record_hash"], seq)`.
- **Disabled (default):** byte-identical to today; `prev_hash`/`record_hash` are never added. This keeps
  the feature strictly additive — every existing assertion in `tests/test_audit.py` on the exact JSON
  shape stays green unchanged.

**New module-level `threading.Lock` around read-head → compute → append → write-head, only when
chaining is enabled.** This is *new and required*, not gold-plating: `gate.py` offloads audit writes to
worker threads (`asyncio.to_thread`), so two threads could both `_read_chain_head` the same `prev_hash`
and silently fork the chain. Today's plain-append path needs no lock (a single short-line `write` syscall
is atomic enough); chaining introduces a read-then-write hazard that did not previously exist.

**The lock does NOT make append + head-write crash-atomic** — it only serializes threads within one
process. If the process crashes *after* the JSONL append but *before* `_write_chain_head`, the head still
points at the prior record; on restart the next write would read that stale `prev_hash`, skip the
already-written last line, and **permanently fork the chain**. Handle this with a reconciliation step,
not a claim of atomicity:
- New helper `_reconcile_chain_head(audit_file: Path, head_path: Path) -> str` — run once on the first
  chained write after process start (cheap: stat + read last line). It compares the head against the
  actual tail of `audit.jsonl`: if `head.seq` and `head.record_hash` already match the last line, the
  head is current; if the file has **more** records than the head knows (the crash-after-append window),
  the head is stale — **re-derive** it from the last on-disk record's `record_hash`/`seq` (the file is the
  source of truth; the just-appended line is real and must be chained from), then `_write_chain_head` the
  repaired head and log a warning. If the tail itself fails `verify_chain` (genuine corruption, not a
  clean crash window), **fail closed** for chained writes (fall back to unchained append + ERROR log)
  rather than forking. `_read_chain_head` (above) calls this on first use per process.

### `utils/audit_chain.py` (new — cold verify/export path, separate from the hot write path)

- `@dataclass class ChainVerifyResult:` `ok: bool`, `record_count: int`, `first_break_line: int | None`,
  `errors: list[str]`.
- `def verify_chain(audit_file: str, head_file: str | None = None) -> ChainVerifyResult` — walks the
  JSONL line by line, recomputes each `record_hash` via the same canonical-JSON method, confirms each
  `prev_hash` equals the previous record's `record_hash` (genesis sentinel on line 1), and confirms the
  **stored head matches the last line's `record_hash`** (catches trailing truncation/deletion). Reused
  by the export CLI and by tests. This module must NOT import `gate.py`/`graph.py` — it is a leaf utility
  alongside `metrics.py`.
- Module docstring records the **retention-purge forward-compat note** (see §6).

### `audit_export.py` (new — top-level, mirrors `metrics.py` placement)

- `def build_evidence_pack(audit_file: str, out_dir: str, start_date: str | None = None,
  end_date: str | None = None, config_path: str = "config.yaml") -> dict` — filters events by
  `timestamp` range (stdlib `datetime`), reuses `metrics.compute_metrics` (no re-aggregation) and
  `verify_chain`, and writes three files into `out_dir`:
  1. `evidence_records.json` — the filtered, already-redacted record set verbatim (contains only
     hashes/aggregates per existing redaction — **no new data exposure**). The export must be a
     **contiguous chain segment** (the records between the date bounds in on-disk order — never a
     non-contiguous filter), so the segment is internally verifiable.
  2. `evidence_summary.csv` — stdlib `csv.DictWriter` flattening of `compute_metrics()` output
     (event breakdown, score stats, retrieval modes, model usage, escalations).
  3. `evidence_manifest.json` — **boundary anchors** so a date-bounded segment verifies without the
     whole file. A date filter breaks naive verification: the first included record's `prev_hash` points
     at an *excluded* earlier record, and the last included record has no independently-held head. The
     manifest records `{segment_start_prev_hash, first_record_hash, last_record_hash, record_count,
     start_date, end_date}` — i.e. the expected `prev_hash` that anchors the segment's first record (an
     auditor treats it as the trusted segment-start anchor, exactly as genesis anchors a full file) and
     the `last_record_hash` as the segment head. (For an unbounded export `segment_start_prev_hash` is the
     genesis sentinel and `last_record_hash` equals the live chain head.)
  4. `verify_instructions.py` — a **fully self-contained, stdlib-only (`json`, `hashlib`)** standalone
     script (string-templated to disk, not imported) that an external auditor runs with zero CyClaw
     install: re-walks `evidence_records.json`, recomputes each `record_hash`, and verifies the
     **segment** against `evidence_manifest.json` — first record's `prev_hash` must equal
     `segment_start_prev_hash`, each subsequent `prev_hash` chains, and the final `record_hash` must equal
     `last_record_hash`. Prints `PASS`/`FAIL`. This is the concrete "no install required" deliverable, and
     it does not false-fail on a legitimately date-bounded pack.
- `def main() -> None` — `argparse` (`--start`, `--end`, `--out`, `--config`), matching `metrics.py`'s
  simplicity; returns/exits per the repo's exit-code convention (`0` ok, `2` operation failed,
  `3` env/config).

### `pyproject.toml`

Add `cyclaw-audit-export = "audit_export:main"` under `[project.scripts]` (`:50-55`), alongside the
existing `cyclaw-metrics = "metrics:main"`.

---

## 3. New `config.yaml` keys

Placed under `logging:` (next to `audit_file`/`audit_fields`, `config.yaml:255-264`, where an operator
configuring the audit log already looks — not in `policy.privacy`, which is about *redaction*, a
different concern):

```yaml
logging:
  level: "INFO"
  log_file: "logs/cyclaw.log"
  audit_file: "logs/audit.jsonl"
  hash_chain_enabled: false                            # opt-in tamper-evidence (chain each record to the prior hash)
  audit_chain_head_file: "logs/audit_chain_head.json"  # current chain head, atomically written
  audit_fields: { ... unchanged ... }
```

**Default `false` — justification:** (a) it is an on-disk **format change** (two new fields per record)
that external tooling parsing `audit.jsonl` should opt into knowingly; (b) it adds a write-lock + extra
file I/O on the per-query hot path that the home-lab default user (per `config.yaml`'s own framing) does
not need; (c) it is one YAML line to enable for the regulated segment that does. This matches the
disabled-by-default convention of every other CyClaw capability (`sync`/`agentic`/`guardrails.enabled`).

---

## 4. New / changed signatures

- `utils/logger.py`: `_canonical_json(record: dict) -> str`, `_chain_head_path(cfg: dict) -> Path`,
  `_read_chain_head(path: Path) -> str`, `_write_chain_head(path: Path, record_hash: str, seq: int) -> None`.
  `audit_log(event: dict, config_path: str = "config.yaml")` — **signature unchanged**, additive behavior.
- `utils/audit_chain.py`: `ChainVerifyResult` dataclass; `verify_chain(audit_file: str, head_file: str | None = None) -> ChainVerifyResult`.
- `audit_export.py`: `build_evidence_pack(...) -> dict` (returns a manifest dict for testability); `main() -> None`.

---

## 5. Tests

- Extend `tests/test_audit.py` with `class TestHashChain` (mirror the existing `TestAuditLog` style):
  `test_chaining_disabled_by_default_no_new_fields`, `test_first_record_chains_from_genesis`,
  `test_second_record_chains_from_first`, `test_chain_survives_concurrent_writes` (threads call
  `audit_log` concurrently with chaining on; the file must verify clean — exercises the lock),
  `test_tampered_record_detected` (hand-edit a fixture line → `verify_chain().ok is False`, correct
  `first_break_line`), `test_deleted_record_detected` (drop a middle line → detected),
  `test_head_file_written_atomically` (no surviving `.tmp`),
  `test_stale_head_reconciled_after_crash_window` (append a line but leave the head pointing at the prior
  record — simulating a crash between append and head-write — then assert the next `audit_log` reconciles
  the head from the on-disk tail and the resulting chain verifies clean, no fork),
  `test_corrupt_tail_fails_closed` (genuinely corrupt the last line → next chained write falls back to
  unchained append + ERROR log rather than forking).
- New `tests/test_audit_chain.py` — `verify_chain()` against hand-built fixtures (valid, genesis-only,
  corrupted hash, missing head, head/file seq mismatch).
- New `tests/test_audit_export.py` — `test_evidence_pack_creates_all_files` (records, summary, manifest,
  verify script), `test_evidence_pack_date_filtering_is_contiguous_segment`,
  `test_manifest_anchors_match_segment_bounds`, `test_evidence_pack_csv_matches_compute_metrics`,
  `test_generated_verify_script_is_self_contained` (run the emitted `verify_instructions.py` as a
  subprocess with only stdlib on the path — proves the no-install claim *and* that a date-bounded segment
  verifies clean against the manifest, not a false-fail), `test_cli_entry_point_main`.

---

## 6. Edge cases & forward-compat (must be in the doc and the code comments)

- **Genesis:** no head file and/or no `audit.jsonl` → first record's `prev_hash` is `"0"*64`.
- **Enable mid-deployment:** the first chained record after enabling is genesis; pre-existing history is
  **not** retroactively chained (it cannot be — there is no way to prove untampered history that predates
  the feature). The evidence pack must state "chain covers records from `<chain_start_timestamp>` onward".
- **Log rotation:** CyClaw implements no rotation today (none found in code). The chain is logically
  continuous across an operator-performed rotation; the verifier must be pointed at the ordered set of
  rotated files. This is a **documentation note in `verify_instructions.py`**, not a new code path.
- **Retention-purge tension (out of scope to build):** `docs/PSYCLAW_FEATURE_IDEAS.md` item #2 (TTL
  purge) would delete old lines, which breaks every later record's `prev_hash`. Document in
  `utils/audit_chain.py`'s module docstring that a future chain-aware purge must either (a) re-anchor at
  the new first surviving record via a `purge_marker` record (`{purged_count, cutoff_date, new_genesis:
  true}`) written into the new head, or (b) archive purged records to a separate file before deletion so
  they remain independently verifiable. **Forward-compat note only — no code now.**

---

## 7. Verification commands

```bash
cd /home/user/CyClaw
GROK_API_KEY=dummy python -m pytest tests/test_audit.py tests/test_audit_chain.py tests/test_audit_export.py -v
GROK_API_KEY=dummy python -m pytest tests/ -q --cov=utils.logger --cov=utils.audit_chain --cov=audit_export --cov-report=term-missing
# enable chaining in a throwaway config, exercise end-to-end + external verify:
python -c "import yaml; c=yaml.safe_load(open('config.yaml')); c['logging']['hash_chain_enabled']=True; yaml.safe_dump(c, open('/tmp/cfg_chain.yaml','w'))"
python -c "from utils.logger import audit_log; audit_log({'event':'test'}, '/tmp/cfg_chain.yaml')"
python -m audit_export --config /tmp/cfg_chain.yaml --out /tmp/evidence_pack
python /tmp/evidence_pack/verify_instructions.py /tmp/evidence_pack/evidence_records.json
ruff check utils/logger.py utils/audit_chain.py audit_export.py
mypy utils/audit_chain.py audit_export.py
```

---

## 8. Ponytail self-check

- **YAGNI** — one signing method (SHA-256 hash chain), hardcoded; no pluggable "signature backend"
  abstraction, no retroactive-chaining-of-old-logs feature (documented as a known limitation only).
- **stdlib-first** — `hashlib`, `json`, `csv`, `dataclasses`, `threading.Lock`, `argparse` only; **zero
  new dependencies** (explicitly no PDF library — "signed" = the hash chain).
- **Minimal abstraction** — four small functions in `utils/logger.py` (which already owns `audit_log`)
  plus one leaf module for the cold verify/export path. The split is justified: the hot write path
  (every query) stays lean; the cold path's imports never load on the common chaining-disabled path.
- **No half-measures** — the concurrent-write race is identified and closed with the lock; genesis,
  rotation, missing/corrupt head, and the purge-interaction are all addressed, not just the happy path.
