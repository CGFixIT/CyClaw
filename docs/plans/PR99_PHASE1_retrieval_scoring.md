# PR #99 Backlog — Phase 1 Implementation Plan: Retrieval Scoring Correctness

> **Scope:** Findings **#1** (Chroma L2/cosine metric mismatch) and **#6** (single-path
> fallback uses non-RRF scores against `min_score`).
> **Parent:** `docs/ACTION_PLAN_PR99_2026-06-20.md` (PR #106), findings catalogued in PR #99.
> **Why these two together:** they are the same defect — *what number reaches the
> `route_by_score` gate* — seen from two angles. Fixing one without the other just
> moves the miscalibration. They must land in **one** change with a single end-to-end
> re-validation of the `min_score` gate.
>
> **This document is a plan, not the implementation.** It is detailed enough to execute
> directly and to review the eventual code PR against.

---

## 0. TL;DR for reviewers

- ChromaDB collections are created with the **default `l2`** space, but embeddings are
  **L2-normalized**, and downstream code does `score = 1 - distance` assuming cosine.
  Result: semantic scores live on a wrong, non-cosine scale.
- When only one retrieval path returns, `hybrid_search` returns **raw** scores (semantic
  `1-distance`, or unbounded BM25) instead of RRF — yet `route_by_score` compares them to
  a `min_score` (`0.028`) that was tuned for **RRF** magnitudes.
- Fix = set `hnsw:space: cosine` at index build, **rebuild the index**, give degraded
  single-path results a comparably-scaled score, and **re-validate `min_score`** against
  the committed corpus via the existing RAG smoke before merge.

---

## 1. Finding #1 — ChromaDB distance metric mismatch

### 1.1 Problem statement
Semantic similarity scores surfaced to the router, the API response, the UI, and the audit
log are computed on a distance scale that is **not** cosine, despite the code treating it
as cosine.

### 1.2 Evidence (current code on `main`)
- `retrieval/indexer.py:112` — `collection = client.create_collection(collection_name)`
  with **no** `metadata={"hnsw:space": ...}`. ChromaDB therefore defaults to **`l2`**
  (squared Euclidean).
- `retrieval/embeddings.py:56,68` — both query and corpus embeddings use
  `normalize_embeddings=True` → **unit-length** vectors.
- `retrieval/hybrid_search.py:96` — `score = 1 - results["distances"][0][i]`, i.e. the code
  assumes `distance ∈ [0,1]` (cosine distance).

### 1.3 Root-cause analysis
For two **unit** vectors, squared-L2 distance `‖a-b‖² = 2 - 2·cos(a,b)`, which ranges
`0…4` as cosine goes `+1…-1`. So `score = 1 - distance` ranges **`-3…+1`**, not `0…1`.
In practice positive cosine similarities (~`0.3–0.7`) map to L2² ~`0.6–1.4`, i.e.
`score` ~`-0.4…+0.4` — a compressed, partly-negative band that does not mean "cosine
similarity" anywhere.

### 1.4 Impact / blast radius
- **`semantic_score`** in every API/UI/audit payload is wrong (misleading provenance).
- **Single-path semantic fallback** (see #6) compares this raw score to `min_score` → gate
  misfires.
- **Fused (RRF) path is mostly insulated**: `route_by_score` gates on the RRF `top_score`,
  which is **rank-based** (`Σ 1/(rrf_k+rank)`), not the raw distance. This is *why the
  product still works today* and why this is HIGH-but-not-catastrophic. Document this
  explicitly so reviewers don't expect the gate behavior to change for the common path.

### 1.5 Proposed fix
```python
# retrieval/indexer.py — in build_index(), replace the create_collection call
collection = client.create_collection(
    collection_name,
    metadata={"hnsw:space": "cosine"},   # unit vectors → distance = 1 - cos ∈ [0,2]
)
```
With cosine space, `distance = 1 - cos` (range `0…2`), so `score = 1 - distance = cos`
(range `-1…1`) — now genuinely cosine similarity, matching the code's assumption.

> **Do not** also try to "fix" `hybrid_search.py:96`. Once the space is cosine, the existing
> `1 - distance` is correct. The only code change is the collection metadata; the rest is a
> rebuild + re-validation.

### 1.6 Implementation steps
1. Add the `metadata={"hnsw:space": "cosine"}` kwarg to `create_collection`.
2. **Rebuild the index:** `python -m retrieval.indexer` (regenerates `index/chroma_db` +
   `index/bm25.json`). Note the BM25 side is unaffected; only Chroma changes.
3. Capture before/after `semantic_score` distributions for the committed corpus
   (`data/corpus/cyclaw_overview.md`) for the PR description.
4. Re-evaluate `min_score` (see §2.5 — shared gate work with #6).

### 1.7 Test strategy
- **New unit test** (`tests/test_hybrid_search.py`): assert that after a build, semantic
  scores for a known-relevant query land in a cosine range (`-1 ≤ score ≤ 1`) and that the
  top hit's score is meaningfully positive.
- **Reuse** `tests/test_rag_integration.py` / `tests/ci_rag_smoke.py` — they rebuild the
  index, so they exercise the cosine path automatically. Add an assertion on the score
  scale there.
- **CI:** the `Real RAG Query Smoke` step already rebuilds + queries; confirm it stays
  green with the re-tuned `min_score`.

### 1.8 Migration / rollout
- **Index rebuild is mandatory** — existing `index/chroma_db` was written under `l2` and the
  space is fixed at collection creation; it cannot be changed in place.
- Operators must run `python -m retrieval.indexer` after pulling. Call this out in the PR
  body and in `docs/SETUP.md`.

### 1.9 Risk & rollback
- **Risk:** the re-scaled scores shift which queries pass `min_score` on the **single-path**
  branch; mitigated by doing #6 + gate re-tune in the same PR.
- **Rollback:** revert the one-line metadata change and rebuild — fully reversible.

### 1.10 Acceptance criteria
- [ ] `create_collection` uses `hnsw:space: cosine`.
- [ ] Index rebuilt; smoke green.
- [ ] Top semantic hit for a relevant query has cosine score in a sane positive band.
- [ ] PR body documents before/after score distributions and the reindex requirement.

---

## 2. Finding #6 — Single-path fallback scoring vs `min_score`

### 2.1 Problem statement
Under **degraded retrieval** (one path empty), the score the router sees is on a different,
uncalibrated scale than the `min_score` threshold, so the confidence gate misfires —
typically passing low-quality results as "high confidence".

### 2.2 Evidence (current code on `main`)
- `retrieval/hybrid_search.py:144-149`:
  ```python
  if not semantic_hits and not keyword_hits:
      return []
  if not semantic_hits:
      return keyword_hits      # raw BM25 scores (can be ≫ 1)
  if not keyword_hits:
      return semantic_hits     # raw 1 - distance
  ```
- `graph.py` `route_by_score_node` compares `top_score` to `cfg["retrieval"]["min_score"]`
  (`config.yaml: min_score: 0.028`).
- The fused branch builds **RRF** scores (`Σ 1/(rrf_k+rank)`, with `rrf_k: 60`) → top
  scores ~`0.016–0.033`. `min_score = 0.028` is clearly tuned to **that** RRF band.

### 2.3 Root-cause analysis
`min_score` is calibrated for RRF magnitudes (~hundredths). But:
- A surviving **BM25-only** result can score `2`, `5`, `>10` — astronomically above `0.028`
  → always "high confidence", even for a weak keyword coincidence.
- A surviving **semantic-only** result post-#1 is a cosine value ~`0.3` → also above `0.028`
  → effectively no gate.
So in degraded mode the gate is a no-op, defeating the "vault miss → confirm" UX.

### 2.4 Proposed fix (options — pick in the code PR)
**Option A (preferred): always emit an RRF-scaled score.** Even single-path, assign
`score = 1/(rrf_k + rank)` so the gate always sees the same scale it was tuned for:
```python
if not semantic_hits:
    return _as_rrf_scaled(keyword_hits)   # score := 1/(rrf_k + rank), preserve raw in keyword_score
if not keyword_hits:
    return _as_rrf_scaled(semantic_hits)  # ditto, preserve raw in semantic_score
```
Raw values stay available in `semantic_score`/`keyword_score` for provenance; only the
gating `score` is normalized.

**Option B: per-mode thresholds.** Add `min_score_semantic` / `min_score_keyword` to config
and branch in `route_by_score`. More config surface, more to tune; only choose if product
wants distinct degraded-mode behavior.

### 2.5 Shared gate re-validation (with #1)
After #1's reindex **and** the #6 change, re-derive `min_score` empirically:
1. Run the corpus queries (smoke + a handful of known miss/hit queries).
2. Record `top_score` for clear hits vs clear misses in fused **and** each single-path mode.
3. Pick `min_score` (and any per-mode thresholds) that separate them; document the table.

### 2.6 Implementation steps
1. Implement Option A `_as_rrf_scaled` helper (or Option B config + branch).
2. Keep raw scores in the per-mode provenance fields.
3. Re-tune `min_score` per §2.5.
4. Add degraded-mode tests (below).

### 2.7 Test strategy
- `tests/test_hybrid_search.py`: add `test_semantic_only_score_scale` and
  `test_keyword_only_score_scale` asserting the gating `score` is on the RRF scale
  (Option A) or that the right per-mode threshold is applied (Option B).
- `tests/test_graph.py`: add a degraded-retrieval routing test — a keyword-only result that
  is a weak match should **not** auto-route to `local_llm` as high-confidence.
- Existing `TestRRFFusion` cases must stay green (fused path unchanged).

### 2.8 Risk & rollback
- **Risk:** changing degraded-mode scoring alters routing for some queries; bounded to the
  single-path branch and covered by new tests. **Rollback:** revert helper + threshold.

### 2.9 Acceptance criteria
- [ ] Single-path results expose a gate `score` on the same scale as `min_score`.
- [ ] Raw per-mode scores still present for provenance.
- [ ] `min_score` re-tuned with a documented hit/miss separation table.
- [ ] New degraded-mode unit + routing tests pass; fused-path tests unchanged.

---

## 3. Sequencing, dependencies, effort

| Step | Depends on | Est. |
|------|-----------|------|
| #1 metadata change | — | 15 min |
| Index rebuild + score capture | #1 | 15 min |
| #6 single-path RRF scaling | — (code), but validate after #1 | 30–45 min |
| `min_score` re-tune + tables | #1 + #6 | 30 min |
| Tests (unit + routing + smoke assertions) | above | 45 min |

**Land order:** one PR containing #1 + #6 + tests + the re-tuned `min_score`. Do **not**
split — the gate must be validated once against final score semantics.

## 4. Verification commands
```bash
# Rebuild under cosine and exercise the full retrieval path
GROK_API_KEY=dummy python -m retrieval.indexer
GROK_API_KEY=dummy python -m tests.ci_rag_smoke
GROK_API_KEY=dummy pytest tests/test_hybrid_search.py tests/test_graph.py -q --tb=short
```

## 5. Out of scope (tracked elsewhere)
- Injection-defense parity (#2) → Phase 2.
- Network/auth posture (#3/#4/#5) → Phase 3.
- Audit redaction consolidation (#10) → Phase 4.
