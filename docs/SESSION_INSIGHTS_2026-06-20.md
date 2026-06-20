# Session Insights — 2026-06-20

Durable lessons from the PR #99 backlog remediation + post-merge review session.
Captured for future Claude sessions working on CyClaw.

---

## What shipped this session

| PR | Scope | Outcome |
|----|-------|---------|
| #100 | `constraints.txt` typo `aoisignal`→`aiosignal` | merged |
| #101 | `metrics.py` add `encoding="utf-8"` | merged |
| #102 | `gate.py` remove unused `FastAPIHTTPException` | merged |
| #103 | `indexer.py` `chunk_document` step-clamp guard | merged |
| #104 | `ci.yml` add MCP/personality test files + cov | merged |
| #106 | Action plan + Phase-0 fixes (#8/#9/#11) | **closed unmerged** |
| #112 | Phase 4 — audit redaction (#10) | merged |
| #113 | Phase 2 — injection-scanner parity (#2/#7/#12) | merged |
| #114 | Phase 1 — cosine ChromaDB space (#1); #6 deferred | merged |
| #115 | Phase 3 — TrustedHost (#3) + fail-closed auth (#4) | open (CI) |
| #118 | `[Bug_Fixes]` — post-merge review of last 2 merges | open (draft) |

---

## Hard-won technical lessons

### 1. Option A (auto-generate secret) inherently trips CodeQL — twice
An ephemeral auto-generated API key **cannot** be made CodeQL-clean:
- Logging the key → "clear-text logging of sensitive information" (high)
- Writing it to a 0600 file → "clear-text storage of sensitive information" (high)

There is no middle ground. **Fail-closed (Option B) is the only CodeQL-clean design**
for an unset-secret path: refuse the endpoint (401), generate/log/store nothing.
When a security choice keeps tripping the scanner, stop iterating and switch
designs rather than chasing suppressions.

### 2. The RAG smoke corpus is tiny — single-path scoring fixes break it
`tests.ci_rag_smoke` rebuilds the index over a 1–2 chunk corpus. With so few docs:
- BM25 IDF goes **negative** (single-doc corpus) → keyword path returns empty
- Retrieval collapses to **single-path semantic**
- Any change that rescales RRF scores can push `top_score` below `min_score`
  (0.028) → "vault miss" → smoke fails

**Cosine space (#1) is ranking-invariant and smoke-safe. RRF re-scaling (#6) is NOT** —
it needs a `min_score` re-tune decision from the maintainer before it can land.
#6 remains deferred.

### 3. Windows CI: SQLite + TemporaryDirectory = WinError 32
`PersonalityManager` holds an open sqlite connection. On Windows you cannot delete
an open file, so `tempfile.TemporaryDirectory()` cleanup raises `PermissionError`.
Fix: `TemporaryDirectory(ignore_cleanup_errors=True)`. Applied to all 4 call sites
in `test_personality_changes.py`.

### 4. Suppression conventions differ by scanner
- **DevSkim**: inline `# DevSkim: ignore DS162092,DS137138` works reliably
- **CodeQL**: no reliable inline suppression — alerts must be dismissed via the
  Security UI, or (better) the underlying pattern removed

### 5. Rebase + force-push auto-restarts CI
Rebasing a PR branch onto latest main and `git push --force-with-lease`
automatically re-triggers the CI workflow (new head SHA). No manual
`rerun_workflow_run` needed. Verified across #113/#114/#115.

---

## Process lessons

- **Verify findings against main HEAD before acting.** The post-merge review flagged
  8 issues; one (#3, "undefined `RetrievedDoc`") was **already a defined `TypedDict`
  at `graph.py:55`** — the finder was wrong. Always read current code before writing
  a fix or a plan. PR #118's template bakes this "assess-then-implement" gate in.
- **Plan PRs vs code PRs**: the user prefers lean change-only PRs ("just the changes
  being merged"). Plan-only docs were superseded by code PRs and closed.
- **Don't push to main via GitHub MCP when a feature branch + open PR exist** —
  creates add/add rebase conflicts. Let the PR merge carry changes into main.
- **Webhooks don't deliver everything**: CI *success* and new-push events are never
  pushed. Only failures/comments/merges arrive. Can't auto-confirm greens — must
  fetch on demand.

---

## Open / deferred items

- **#6 (single-path RRF scaling)** — deferred; needs maintainer `min_score`
  re-tune decision before it can become a PR.
- **#115** — open, CI pending after fail-closed (Option B) rewrite.
- **#118** — draft; 7 of 8 review findings VALID (finding #3 dropped as N/A).

---

## Environment quirks (confirmed this session)

- Light-dep local test install (no chromadb/torch):
  `pip install --ignore-installed PyYAML fastapi==0.137.2 pydantic==2.13.4 httpx==0.28.1 pytest==9.1.0 pytest-asyncio==1.4.0 rank-bm25==0.2.2 nltk==3.9.4 numpy==1.26.4`
- Offline test run: `export GROK_API_KEY=dummy; python -m pytest <files> -o addopts="" -p no:cacheprovider -q`
- Retrieval-stack tests (chromadb/sentence-transformers) rely on CI, not local.
