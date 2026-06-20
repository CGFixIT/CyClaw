#!/usr/bin/env python3
"""terminal.html API emulation — exercises the exact HTTP fetch lifecycle that
static/terminal.html performs in the browser, using httpx from the venv.

Verifies:
  1. GET /health (3 s timeout, checks index_ready + graph_ready)
  2. POST /query  vault-hit path  (corpus query → needs_confirm=False, hit_count>0)
  3. POST /query  vault-miss path (off-topic → needs_confirm=True, no hit)
  4. POST /query  offline path    (off-topic + user_confirmed_online=False → offline-best-effort)
  5. GET /soul    (version present, soul text non-empty)

Response field assertions match what terminal.html's JS reads:
  - data.needs_confirm
  - data.answer, data.model_used, data.retrieval_mode, data.hit_count
  - data.confirm_message
  - soul.version, soul.soul

Usage (called from verify.sh while server is running):
    python terminal_emulation.py <base_url>
    e.g. python terminal_emulation.py http://localhost:8787
"""

import json
import sys


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787"  # DevSkim: ignore DS162092,DS137138 — loopback-only by design (api.host in config.yaml)

    try:
        import httpx
    except ImportError:
        print("httpx not installed; skipping terminal emulation (install with pip install httpx)")
        return 0

    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {label}" + (f"  [{detail}]" if detail else ""))
        if not ok:
            failures += 1

    def show_response(label: str, data: dict) -> None:
        """Print the fields terminal.html reads, in terminal display order."""
        print(f"       answer       : {str(data.get('answer',''))[:120]}")
        print(f"       model        : {data.get('model_used')}")
        print(f"       mode         : {data.get('retrieval_mode')}")
        print(f"       hits         : {data.get('hit_count')}")
        print(f"       needs_confirm: {data.get('needs_confirm')}")
        if data.get("confirm_message"):
            print(f"       confirm_msg  : {data.get('confirm_message')}")

    print(f"=== terminal.html API emulation → {base} ===")
    print()

    with httpx.Client(base_url=base, timeout=10.0) as client:

        # ── 1. GET /health (terminal.html uses 3 s timeout) ──────────────────
        print("[1] GET /health (terminal.html status bar)")
        try:
            r = client.get("/health", timeout=3.0)
            d = r.json()
            idx = d.get("index_ready", False)
            grp = d.get("graph_ready", False)
            sts = d.get("status", "?")
            print(f"       status       : {sts}")
            print(f"       index_ready  : {idx}")
            print(f"       graph_ready  : {grp}")
            check("/health index_ready + graph_ready", idx and grp,
                  f"status={sts}")
        except Exception as exc:
            check("/health", False, repr(exc))
        print()

        # ── 2. POST /query — vault-hit path ───────────────────────────────────
        CORPUS_QUERY = "What fusion method does CyClaw use to blend semantic and keyword results?"
        print(f"[2] POST /query  (vault-hit — terminal.html normal flow)")
        print(f"       query: {CORPUS_QUERY}")
        try:
            r = client.post("/query", json={"query": CORPUS_QUERY})
            d = r.json()
            show_response("vault-hit", d)
            check("/query vault-hit: needs_confirm=False",
                  d.get("needs_confirm") is False,
                  f"got needs_confirm={d.get('needs_confirm')}")
            check("/query vault-hit: hit_count > 0",
                  (d.get("hit_count") or 0) > 0,
                  f"hit_count={d.get('hit_count')}")
            check("/query vault-hit: model_used present",
                  bool(d.get("model_used")),
                  f"model_used={d.get('model_used')}")
            check("/query vault-hit: retrieval_mode present",
                  bool(d.get("retrieval_mode")),
                  f"retrieval_mode={d.get('retrieval_mode')}")
        except Exception as exc:
            check("/query vault-hit", False, repr(exc))
        print()

        # ── 3. POST /query — vault-miss (needs_confirm flow) ─────────────────
        OFFTOPIC_QUERY = "What is the boiling point of water at high altitude?"
        print(f"[3] POST /query  (vault-miss — terminal.html confirm prompt)")
        print(f"       query: {OFFTOPIC_QUERY}")
        try:
            r = client.post("/query", json={"query": OFFTOPIC_QUERY})
            d = r.json()
            show_response("vault-miss", d)
            check("/query vault-miss: needs_confirm=True",
                  d.get("needs_confirm") is True,
                  f"got needs_confirm={d.get('needs_confirm')}")
        except Exception as exc:
            check("/query vault-miss", False, repr(exc))
        print()

        # ── 4. POST /query — offline-best-effort (user declines Grok) ─────────
        print(f"[4] POST /query  user_confirmed_online=false  (terminal.html 'No' branch)")
        print(f"       query: {OFFTOPIC_QUERY}")
        try:
            r = client.post("/query", json={
                "query": OFFTOPIC_QUERY,
                "user_confirmed_online": False
            })
            d = r.json()
            show_response("offline-best-effort", d)
            check("/query offline: model_used=offline-best-effort",
                  d.get("model_used") == "offline-best-effort",
                  f"model_used={d.get('model_used')}")
        except Exception as exc:
            check("/query offline-best-effort", False, repr(exc))
        print()

        # ── 5. GET /soul (terminal.html soul panel) ──────────────────────────
        print("[5] GET /soul  (terminal.html soul panel)")
        try:
            r = client.get("/soul", timeout=5.0)
            d = r.json()
            ver = d.get("version")
            soul_text = d.get("soul", "")
            print(f"       version      : {ver}")
            print(f"       soul (chars) : {len(soul_text)}")
            print(f"       source       : {d.get('source')}")
            check("/soul version is int", isinstance(ver, int), f"version={ver!r}")
            check("/soul soul text non-empty", len(soul_text) > 50, f"len={len(soul_text)}")
        except Exception as exc:
            check("/soul", False, repr(exc))
        print()

    print()
    if failures:
        print(f"terminal.html emulation FAILED ({failures} check(s))")
        return 1
    print("terminal.html emulation PASSED — all endpoint flows matched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
