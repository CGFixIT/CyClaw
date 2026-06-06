# PsyClaw Suggestions & Fixes for Refactor (v1.3.0)

## Summary
This document tracks the architectural changes, bug fixes, and open issues identified during the v1.3.0 refactor.

## Completed in v1.3.0
- [x] Rate limiting (60 req/min per IP, sliding window)
- [x] Soul SHA-256 drift detection on startup
- [x] Atomic soul writes (backup → DB → disk → memory)
- [x] Expanded to 13 OWASP injection patterns
- [x] interaction_ttl_days extended to 365
- [x] Telemetry kill block moved before any SDK import
- [x] `route_by_score` threshold corrected to 0.028 (RRF scale, not cosine)
- [x] Soul preamble injection hardened (labeled as untrusted context)

## Open Issues / v1.4.0 Targets
- [ ] Dropbox corpus sync (`dropbox_sync.py` placeholder)
- [ ] `plan_node` for multi-hop query decomposition
- [ ] `insightextractor.py` for automated corpus enrichment from query patterns
- [ ] Conversation compaction (rolling summary node)
- [ ] BM25 index SHA-256 integrity verification on load
- [ ] `static/terminal.html` API alignment (currently has endpoint mismatches)
- [ ] Config schema validation on startup (pydantic model for config.yaml)
- [ ] Weighted RRF option (currently equal 1.0/1.0 by design)

## Known Issues
- `static/terminal.html` has API response field mismatches vs current QueryResponse schema
- `vector_weight`/`bm25_weight` in config.yaml are documentation-only; actual weighting is equal
- `min_score` threshold comments reference cosine similarity but value is RRF scale
