# PsyClaw — Dependency Modernization Audit (Python 3.12)

**Date:** 2026-06-13
**Scope:** Re-assess the proposed "hardened" `requirements.txt`, verify every claim against the
live package index + advisory databases, and ship a stable, non-vulnerable, mutually-compatible
set for **Python 3.12** — validated by an actual clean-venv install + import + unit + runtime test.
**Track chosen:** *Conservative-mature* (langgraph 1.1.x + langchain-core 1.3.x).

---

## 1. Verdict in one line

The proposed file was **~70% right in spirit but wrong in specifics**: it added packages the
app doesn't use, shipped a *still-vulnerable* `langchain-core==1.3.2`, and pinned `numpy==2.2.1`
which **breaks ChromaDB**. The set below is what actually installs, imports, and runs on 3.12.

---

## 2. Recommended set (verified-installed on Python 3.12.3)

| Package | Old pin | New pin | Why |
|---|---|---|---|
| fastapi | 0.110.0 | **0.136.3** | starlette ≥1.0.1 → fixes CVE-2025-62727 (Range DoS) + CVE-2026-48710 (BadHost) |
| uvicorn[standard] | 0.27.1 | **0.49.0** | current stable |
| pydantic | 2.6.1 | **2.13.4** | required by fastapi 0.136 (≥2.9); v2 API unchanged for this app |
| pyyaml | 6.0.1 | **6.0.2** | 3.12 wheels / Cython-3 build fix |
| httpx | 0.26.0 | **0.28.1** | current stable |
| langgraph | 0.2.60 | **1.1.10** | latest 1.1.x; >1.0.9 so clear of CVE-2026-28277 |
| langchain-core | 0.3.30 | **1.3.3** | fixes CVE-2026-44843 **and** CVE-2025-68664 (both hit 0.3.30) |
| chromadb | 0.4.22 | **1.5.6** | `PersistentClient/get_collection/query/add` API unchanged |
| sentence-transformers | 2.5.1 | **5.5.1** | `.encode()` API unchanged; needs torch ≥1.11 |
| rank-bm25 | 0.2.2 | **0.2.2** | unchanged; fine on 3.12 |
| numpy | 1.26.4 | **1.26.4** | **kept on 1.x** — numpy 2.x breaks chromadb's onnxruntime dep |
| nltk | 3.9.2 | **3.9.4** | **kept** (used by stemmer); ≥3.9.0 fixes CVE-2024-39705 |
| pytest | 8.0.2 | **9.0.3** | fixes CVE-2025-71176 (insecure temp dir) |
| torch | (absent) | **2.4.1+cpu** | install separately via PyTorch CPU index (see requirements.txt) |
| pytest-asyncio | 0.23.5 | **removed** | zero async tests in the suite |
| matplotlib | 3.8.3 | **removed** | never imported anywhere |

`constraints.txt` pins the **full transitive tree** (incl. `langgraph-checkpoint==4.1.1`,
`starlette==1.3.1`) for reproducible installs.

---

## 3. Why the proposed file / its analysis were wrong

| Claim in the proposed file (or its analysis) | Reality (verified) |
|---|---|
| "langgraph-checkpoint + langgraph-checkpoint-sqlite required for SQLite soul persistence" | **False.** Soul persistence is **stdlib `sqlite3`** (`utils/personality.py:14`). `graph.py` uses only `StateGraph, END` — **no checkpointers**. CVE-2026-27794 / CVE-2026-28277 / CVE-2025-67644 are **real but don't affect this app**. Adding those packages only adds attack surface + `sqlite-vec`/`aiosqlite`/`ormsgpack`. |
| "All CVEs patched" with `langchain-core==1.3.2` | **Still vulnerable.** CVE-2026-44843 affects langchain-core `1.0.0–1.3.2`; fixed in **1.3.3**. The proposed pin shipped a known-vulnerable version. |
| analysis: "1.3.2 ↔ langgraph will fail the resolver" | **Wrong.** langgraph 1.1.x requires `langchain-core <2,>=0.1.52`; they resolve fine. The issue with 1.3.2 was the CVE, not resolution. |
| `numpy==2.2.1` marked "✅ Valid" | **Hard blocker, missed by both.** chromadb → onnxruntime does not support numpy 2.x (`np.float_` removed). Pin **1.26.4**. |
| `pytest==8.3.4` "valid" | **Still vulnerable** to CVE-2025-71176; fixed in **9.0.3**. |
| analysis: pytest-asyncio `asyncio_mode` blocker | **Moot** — there are no async tests; package removed. |
| analysis: "drop nltk" (proposed file removed it) | **Correctly flagged as a blocker** — nltk IS used (`retrieval/stemmer.py`). Kept. |
| "langgraph 1.1.9 / latest 1.1.15" | `1.1.9` exists; **`1.1.15` does not** — latest 1.1.x is **1.1.10**. (Pinned 1.1.10.) |

---

## 4. CVE reference

Fixed / avoided by this upgrade:

| CVE | Package | Affected | Fixed in | Relevance |
|---|---|---|---|---|
| CVE-2026-44843 | langchain-core | ≤0.3.84 and 1.0.0–1.3.2 | 0.3.85 / **1.3.3** | **Old 0.3.30 vulnerable** → fixed |
| CVE-2025-68664 ("LangGrinch") | langchain-core | <0.3.81 | 0.3.81 | **Old 0.3.30 vulnerable** → fixed |
| CVE-2025-62727 | starlette (via fastapi) | older | starlette 0.49.1+ | fixed via fastapi 0.136 |
| CVE-2026-48710 ("BadHost") | starlette (via fastapi) | ≤1.0.0 | starlette 1.0.1+ | fixed via fastapi 0.136 |
| CVE-2025-71176 | pytest | ≤9.0.2 | **9.0.3** | **Old 8.0.2 vulnerable** → fixed |
| CVE-2024-39705 | nltk | ≤3.8.1 | 3.9.0+ | already safe on 3.9.x (kept) |

Real but **not applicable** (app doesn't use checkpointers): CVE-2026-27794 / CVE-2026-28277
(langgraph-checkpoint), CVE-2025-67644 (langgraph-checkpoint-sqlite).

---

## 5. Actual Python 3.12 test results

Clean `python3.12 -m venv`, installed the set above, ran:

| Tier | Result |
|---|---|
| Dependency resolution | ✅ Full tree resolves, **no conflicts** |
| Install | ✅ `pip install` exit 0 (all pins exist on PyPI) |
| Import smoke | ✅ fastapi, pydantic, yaml, httpx, uvicorn, langgraph(.graph StateGraph/END), langchain_core, chromadb (PersistentClient + Settings), sentence_transformers, rank_bm25, numpy, nltk, torch, pytest |
| LangGraph build | ✅ `graph.build_graph(...)` → `CompiledStateGraph` with callable `.invoke` on langgraph 1.1.10 |
| ChromaDB write path | ✅ `PersistentClient` created `index/chroma_db/chroma.sqlite3` |
| FastAPI/uvicorn boot | ✅ "Application startup complete"; `GET /health` → 200 (structured JSON), `GET /` → 200; telemetry-kill block confirmed working against the new SDK versions |
| Unit tests | **24 passed, 1 failed** — see below |
| Live embedding / `/query` end-to-end | ⚠️ **Not exercised in CI**: the test container's network policy blocks `huggingface.co` (403), so `all-MiniLM-L6-v2` couldn't download. This is an environment limit, not a dependency problem; the app is offline-first and requires a pre-cached model in normal operation. |

**The 1 failing test is pre-existing and version-independent.**
`tests/test_stemmer.py::test_tokenize_and_stem_filters_short` asserts
`tokenize_and_stem("a to the") == []`, but `retrieval/stemmer.py`'s filter regex
`^[a-z][a-z0-9_-]{1,}$` keeps any token ≥2 chars (it does no stopword removal), so the result is
`['to','the']`. Reproduced **identically on the old `nltk==3.9.2` pin**, confirming the upgrade
did not cause it. Fixing it is a code/test change, out of scope for this dependency audit —
recommend either tightening the regex to `{2,}` + a stopword set, or correcting the test's
expectation to `['to','the']`.

---

## 6. GitHub state at audit time

- **Dependabot PR #2** (open) bumps langgraph→**1.0.10rc1** (a release candidate — unsuitable for
  a pin), langchain-core→1.3.3, pytest→9.0.3. It targets the right CVEs; this audit supersedes it
  with stable, mutually-tested pins. Safe to close in favor of this branch.
- PR #4 (security audit) and PR #5 (graph refactor) are open and unrelated to dependencies.
- CI is `.github/workflows/codeql.yml` only. No Dependabot **alerts** API is exposed via the
  available tooling; PR #2 is the visible artifact of those alerts.

---

## 7. Operational checklist for the maintainer

1. `pip install torch==2.4.1+cpu --index-url https://download.pytorch.org/whl/cpu`
2. `pip install -r requirements.txt -c constraints.txt`
3. **Rebuild the index** (chromadb 0.4→1.5 format change): delete `index/`, run `python -m retrieval.indexer`
   on a networked machine once to cache `all-MiniLM-L6-v2`.
4. `pytest` — expect 24 pass / 1 pre-existing stemmer failure (see §5).
5. `uvicorn gate:app --host 127.0.0.1 --port 8787`.
