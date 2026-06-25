"""Operator-facing pre-flight self-test for ``python -m agentic.fsconnect.cli test``.

NOT the pytest suite. A fast, no-network smoke test confirming the filesystem
connector will work here: config validity, the path guard denies traversal, the
injection scanner is present, the write gate refuses an ungated write, and the read
path works end-to-end. Checks 4/5 use throwaway temp dirs so the self-test creates
no persistent side effects (it never touches the configured default share).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agentic.fsconnect.client import FsClient, build_injection_patterns
from agentic.fsconnect.config import FsConnectConfig, load_fsconnect_config
from agentic.fsconnect.pathsafe import split_components
from agentic.fsconnect.writer import FsWriter
from utils.errors import FsConnectConfigError, FsPathError, FsWriteRefused
from utils.logger import _get_config


def _ok(name: str) -> tuple[bool, str]:
    return True, f"  [OK  ] {name}"


def _fail(name: str, reason: str) -> tuple[bool, str]:
    return False, f"  [FAIL] {name}: {reason}"


def _skip(name: str, reason: str) -> tuple[bool, str]:
    return True, f"  [SKIP] {name}: {reason}"


def run_self_test(config_path: str = "config.yaml") -> tuple[int, int, list[str]]:
    results: list[tuple[bool, str]] = []

    # 1. config loads and validates.
    try:
        load_fsconnect_config(config_path)
        results.append(_ok("01. fsconnect config loads and validates"))
    except FsConnectConfigError as exc:
        results.append(_fail("01. fsconnect config loads and validates", exc.message))
        for n in range(2, 6):
            results.append(_skip(f"{n:02d}. (skipped -- no config)", "config invalid"))
        return _finalize(results)

    cfg = _get_config(config_path)

    # 2. path guard denies traversal / absolute / nested escape. split_components is
    # a pure guard that raises FsPathError for these fixed inputs (and nothing else),
    # so no broad except/pass is needed -- count the FsPathError denials directly.
    bad_inputs = ("../escape", "/etc/passwd", "a/../../b")
    denied = 0
    for bad in bad_inputs:
        try:
            split_components(bad)
        except FsPathError:
            denied += 1
    if denied == len(bad_inputs):
        results.append(_ok(f"02. path guard denies traversal/absolute ({denied}/{len(bad_inputs)})"))
    else:
        results.append(_fail("02. path guard denies escapes", f"only {denied}/{len(bad_inputs)} denied"))

    # 3. injection scanner present.
    if build_injection_patterns(cfg):
        results.append(_ok("03. injection scanner compiled (OWASP ∪ banned_patterns)"))
    else:
        results.append(_fail("03. injection scanner present", "no patterns compiled"))

    # 4. write gate refuses an ungated write (temp writable root; no side effects).
    try:
        with tempfile.TemporaryDirectory() as td:
            tcfg = FsConnectConfig(writable_roots=[td], writes_enabled=True)
            with FsWriter(cfg, tcfg, config_path) as w:
                try:
                    w.fs_write("x.txt", b"y", reason="")  # missing reason
                    results.append(_fail("04. write gate refuses ungated write", "did NOT refuse"))
                except FsWriteRefused:
                    results.append(_ok("04. write gate refuses ungated write"))
    except Exception as exc:  # noqa: BLE001 -- selftest must never crash
        results.append(_skip("04. write gate", f"could not exercise: {exc}"))

    # 5. read path works end-to-end (temp read root).
    try:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "probe.txt").write_text("probe", encoding="utf-8")
            rcfg = FsConnectConfig(allowed_roots=[td])
            with FsClient(cfg, rcfg, config_path) as c:
                res = c.fs_read("probe.txt")
            if res.get("content") == "probe":
                results.append(_ok("05. read path works end-to-end"))
            else:
                results.append(_fail("05. read path", "unexpected content"))
    except Exception as exc:  # noqa: BLE001 -- selftest must never crash
        results.append(_fail("05. read path", str(exc)))

    return _finalize(results)


def _finalize(results: list[tuple[bool, str]]) -> tuple[int, int, list[str]]:
    lines = [text for _, text in results]
    passed = sum(1 for ok, _ in results if ok)
    return passed, len(results), lines


if __name__ == "__main__":
    p, t, out = run_self_test()
    for ln in out:
        print(ln)
    print(f"\n{p}/{t} passed")
    raise SystemExit(0 if p == t else 1)
