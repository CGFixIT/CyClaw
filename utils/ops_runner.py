"""utils/ops_runner.py – subprocess shim for the out-of-band ``sync`` / ``agentic`` CLIs.

The FastAPI gateway exposes ``POST /ops/sync`` and ``POST /ops/agentic`` so the
browser Soul Console can drive the two out-of-band subsystems. A browser cannot
spawn a subprocess, so the gateway must — but the gateway must NOT *import* those
packages, because architectural isolation of ``sync/`` and ``agentic/`` from
``gate.py`` / ``graph.py`` / ``mcp_hybrid_server.py`` is a hard CyClaw invariant.

This module is that boundary, and nothing more:

* It NEVER imports ``sync`` or ``agentic``. It only builds an argv list and runs
  it with ``subprocess.run([...])`` (list form, no shell) as
  ``python -m sync.cli`` / ``python -m agentic.cli``.
* It accepts only a whitelisted set of actions per subsystem. An unknown action
  raises :class:`OpsError`, which the route maps to HTTP 400 — a caller can never
  smuggle an arbitrary subcommand or flag through.
* User-supplied skill bodies are written to a ``NamedTemporaryFile`` and passed
  via ``--body-file``, never interpolated into argv.

Exit codes are translated to operator-meaningful labels (see the per-subsystem
maps below) so the UI can render failure states — a tripped ``--max-delete`` /
``--max-transfer`` safety fuse, an env/config error, or a refused write — without
re-deriving the meaning of each code.

Exit-code contract (mirrors the docstrings in ``sync/cli.py`` / ``agentic/cli.py``):

    sync:     0 ok · 10 ok+reindex-needed · 1 safety-abort · 2 failed · 3 env/config
    agentic:  0 ok · 2 failed · 3 env/config · 4 write-refused
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - list-form only, no shell, fixed interpreter + whitelisted argv
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Repo root = parent of utils/. The CLIs run as ``python -m sync.cli`` /
# ``agentic.cli``; running with cwd=repo-root puts the ``sync`` / ``agentic``
# packages on the import path without mutating PYTHONPATH for the gateway process.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "config.yaml"
_TIMEOUT_SEC = 120

# action whitelists — the ONLY subcommands a caller may reach.
_SYNC_ACTIONS = frozenset({"status", "test", "sync", "schedule", "unschedule"})
_AGENTIC_ACTIONS = frozenset({"status", "test", "context", "propose-skill", "apply-skill"})
# agentic subcommands that emit JSON on stdout (vs. human text).
_AGENTIC_JSON_ACTIONS = frozenset({"context", "propose-skill", "apply-skill"})

# exit code -> (ok, label)
_SYNC_LABELS: dict[int, tuple[bool, str]] = {
    0: (True, "ok"),
    10: (True, "ok_reindex_needed"),
    1: (False, "safety_abort"),
    2: (False, "failed"),
    3: (False, "env_config"),
}
_AGENTIC_LABELS: dict[int, tuple[bool, str]] = {
    0: (True, "ok"),
    2: (False, "failed"),
    3: (False, "env_config"),
    4: (False, "write_refused"),
}


class OpsError(ValueError):
    """A disallowed action or malformed request. The route maps this to HTTP 400."""


@dataclass
class OpsResult:
    """Normalized result of one CLI invocation, JSON-serializable for the route."""

    subsystem: str
    action: str
    exit_code: int
    ok: bool
    label: str
    stdout: str
    stderr: str
    parsed: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "subsystem": self.subsystem,
            "action": self.action,
            "exit_code": self.exit_code,
            "ok": self.ok,
            "label": self.label,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "parsed": self.parsed,
        }


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a fully-formed, whitelisted argv list. No shell, fixed interpreter."""
    return subprocess.run(  # noqa: S603  # nosec B603 - list-form, no shell, fixed interpreter + whitelisted argv
        argv,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SEC,
        check=False,
    )


def _maybe_json(text: str) -> Any:
    """Parse JSON if the text is JSON, else return None (status/text output)."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _write_body(body: str) -> str:
    """Persist a skill body to a temp file so it is passed via --body-file, never argv."""
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="cyclaw_skill_", delete=False, encoding="utf-8"
    )
    try:
        handle.write(body)
    finally:
        handle.close()
    return handle.name


def run_sync_op(action: str, *, dry_run: bool = False) -> OpsResult:
    """Invoke ``python -m sync.cli <action>`` and normalize the result.

    Only ``dry_run`` is honored, and only for the ``sync`` action (it maps to
    ``--dry-run``). Every other action takes no caller-controlled arguments, so
    there is no surface for argument injection.
    """
    if action not in _SYNC_ACTIONS:
        raise OpsError(f"Unknown sync action: {action!r}")

    argv = [sys.executable, "-m", "sync.cli", "--config", str(_CONFIG_PATH), action]
    if action == "sync" and dry_run:
        argv.append("--dry-run")

    proc = _run(argv)
    ok, label = _SYNC_LABELS.get(proc.returncode, (False, "unknown"))
    return OpsResult("sync", action, proc.returncode, ok, label, proc.stdout, proc.stderr)


def run_agentic_op(
    action: str,
    *,
    pr: int | None = None,
    issue: int | None = None,
    no_diff: bool = False,
    name: str | None = None,
    desc: str | None = None,
    body: str | None = None,
    reason: str | None = None,
    confirm: bool = False,
) -> OpsResult:
    """Invoke ``python -m agentic.cli <action>`` and normalize the result.

    ``context`` takes an optional ``--pr`` / ``--issue`` selector (defaults to
    ``--repo``). ``propose-skill`` / ``apply-skill`` require ``name`` + ``desc``;
    ``apply-skill`` additionally requires a non-empty ``reason`` (the registry
    governance gate) and only adds ``--confirm`` when the caller set it — calling
    apply without confirm reaches the CLI's own refusal path (exit 4), which is
    surfaced verbatim rather than masked.

    Validation raises happen before the subprocess launch. All ``proc`` usage
    lives INSIDE the try so there is no post-``finally`` reference to an unbound
    name: if ``_run`` raises (e.g. ``subprocess.TimeoutExpired``), the ``finally``
    cleans up the temp body-file and the exception propagates before any result is
    read. The body-file is unlinked on every exit path (return or raise).
    """
    if action not in _AGENTIC_ACTIONS:
        raise OpsError(f"Unknown agentic action: {action!r}")
    if action in {"propose-skill", "apply-skill"} and (not name or not desc):
        raise OpsError(f"{action} requires both name and desc")
    if action == "apply-skill" and not (reason and reason.strip()):
        raise OpsError("apply-skill requires a non-empty reason")

    argv = [sys.executable, "-m", "agentic.cli", "--config", str(_CONFIG_PATH), action]
    body_file: str | None = None
    try:
        if action == "context":
            if pr is not None:
                argv += ["--pr", str(pr)]
            elif issue is not None:
                argv += ["--issue", str(issue)]
            else:
                argv.append("--repo")
            if no_diff:
                argv.append("--no-diff")
        elif action in {"propose-skill", "apply-skill"}:
            # name/desc validated above; both are required, so they are non-None here.
            # Use the --opt=value form (not two argv elements) so a value that
            # begins with '-' is bound to its option rather than being reparsed by
            # the child argparse as a separate flag. name is additionally slug-
            # validated in agentic.registry, but desc/reason are free text and can
            # legitimately start with '-'.
            argv += [f"--name={name}", f"--desc={desc}"]
            if body:
                body_file = _write_body(body)
                argv += ["--body-file", body_file]
            if reason:
                argv += [f"--reason={reason}"]
            if action == "apply-skill" and confirm:
                argv.append("--confirm")

        proc = _run(argv)
        ok, label = _AGENTIC_LABELS.get(proc.returncode, (False, "unknown"))
        parsed = _maybe_json(proc.stdout) if (ok and action in _AGENTIC_JSON_ACTIONS) else None
        return OpsResult("agentic", action, proc.returncode, ok, label, proc.stdout, proc.stderr, parsed)
    finally:
        if body_file:
            Path(body_file).unlink(missing_ok=True)
