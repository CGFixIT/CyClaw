# Archived research input — Insight-Extractor PMF analysis (PR #391)

> **Provenance & status — read first.**
> This document is an **archive of an external comment** left by the repo owner (`cgfixit`) on
> PR #391 on 2026-06-30, saved here at the owner's explicit request ("save to memory … in .md
> format"). It is the output of an *emulated* `insight-extractor` run over a research thread and is
> reproduced for traceability — **it is not vetted project knowledge.**
>
> - The statistics, breach-cost figures, and external citations below are **single-source and largely
>   unverified.** Do **not** cite them as fact in CyClaw docs or sales material without independent
>   verification.
> - Where this analysis fed real changes, only the **independently web-verified** subset was used and
>   is now reflected in `docs/planning/README.md` and `02_security_verification_suite.md`:
>   - ✅ Shadow AI: 66% used workplace AI believing it wasn't permitted; 89% first adopted AI outside
>     work (Wakefield / PagerDuty 2026).
>   - ✅ Memory poisoning: >95% injection success rate; persistent false beliefs (arXiv 2601.05504 /
>     MINJA; Lakera 2026).
>   - ❌ "91% discover AI agent activity after the fact (Forrester 2026)" — **could not verify;
>     excluded** from the docs. The pre-existing 88% / 82% figures (web-verified earlier) were kept.
>   - ❌ Breach-cost figures ($670K, $3.31M, etc.), "96% of incidents involved blackmail," and the
>     86-URL appendix — unverified single-source; **excluded** from the docs.
> - This archive is deliberately placed in `docs/planning/_research/`, **not** `docs/memories/`, so the
>   memory-consolidation skill does not ingest unverified external content as project knowledge.

---

## Actionable substance extracted (the part that drove doc changes)

The analysis flagged four buyer-resonance gaps in the planning docs. All four were addressed as
**documentation-only** refinements (no architecture/code change):

1. **Buyer/governance vocabulary** — the docs led with internal architecture terms ("soul",
   "sandbox") over buyer language. → `README.md` "Why these three" reweighted toward governance,
   provable compliance, and data sovereignty.
2. **Memory-poisoning not named as a threat** — highest-severity unaddressed-by-most vector for the
   law/medical/accounting ICP. → Added (verified-stat) memory-poisoning framing to `README.md` and a
   dedicated callout in `02_security_verification_suite.md`, noting CyClaw **already** defends it
   (`Memory/Persistence Manipulation` banned-pattern category + `utils/personality.py` soul gate) and
   Feature 2 **proves** it.
3. **Shadow-AI stat hook missing** — → Added an accurately-cited shadow-AI lede (66% / 89%) to
   `README.md` framing the "client data can't leave the building" value prop.
4. **No mock `cyclaw-verify` output** — Feature 2's console script is the most buyer-demonstrable
   artifact. → Added a clearly-labeled illustrative (mock) `cyclaw-verify` report to
   `02_security_verification_suite.md`.

---

## Raw comment (verbatim, as received — unverified)

The full original comment — including the keyword tables, high-signal-sentence ranking, PMF gap flags,
and the 86-URL source appendix — is preserved in the **PR #391 comment thread** on GitHub
(https://github.com/cgfixit/CyClaw/pull/391), which is the canonical, timestamped, authorship-attributed
record. It is intentionally **not duplicated byte-for-byte here** to avoid (a) re-publishing ~80
unvetted external URLs into the repo tree as if endorsed, and (b) drift between two copies. The
analytical substance that mattered is captured above and reflected in the planning docs; the GitHub
thread holds the complete original for anyone who needs it verbatim.
