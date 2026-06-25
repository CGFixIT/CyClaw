"""Minimal, low-risk OS integration seed: ``reveal`` a folder in the file manager.

Out-of-band and operator-run only (``python -m agentic.fsconnect.cli reveal``): opens
a writable root in the platform file manager via an argv-list subprocess -- never a
shell, never the request path. This is the deliberately small seed for the deferred
OS-integration roadmap (a terminal.html "open file share" button would need a
request-path endpoint and gets its own security review; see the roadmap doc).

Never imported by gate.py / graph.py / mcp_hybrid_server.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # noqa: S404 -- argv-list file-manager launch only; never shell=True
import sys
from pathlib import Path

from utils.errors import FsConnectRuntimeError


def _file_manager_argv(path: str) -> list[str]:
    if os.name == "nt":  # pragma: no cover - Windows only
        return ["explorer", path]
    if sys.platform == "darwin":  # pragma: no cover - macOS only
        return ["open", path]
    return ["xdg-open", path]


def reveal(path: str) -> dict:
    """Open ``path`` in the OS file manager. Returns a small result dict."""
    p = Path(path)
    if not p.exists():
        raise FsConnectRuntimeError(f"path does not exist: {path}", details={"path": path})
    argv = _file_manager_argv(str(p))
    exe = shutil.which(argv[0])
    if exe is None:
        raise FsConnectRuntimeError(
            f"file manager {argv[0]!r} not found on PATH",
            details={"looked_for": argv[0]},
        )
    try:
        subprocess.run([exe, str(p)], check=False, timeout=10)  # noqa: S603 -- argv list, no shell
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FsConnectRuntimeError("failed to launch file manager",
                                    details={"error": str(exc)}) from exc
    return {"revealed": str(p), "via": argv[0]}


__all__ = ["reveal"]
