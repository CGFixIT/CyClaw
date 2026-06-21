"""Read-only GitHub CLI (`gh`) subprocess wrapper for the CyClaw agentic layer.

Responsibilities:
  - Locate and version-check the ``gh`` binary (configurable floor).
  - Build argv for READ-ONLY operations only (pr/issue/repo view+list, pr diff).
  - Run ``gh`` with captured output and parse JSON where applicable.
  - Emit an audit event via ``utils.logger.audit_log`` for every call.

Hard guarantees (mirrors sync/runner.py):
  - argv is ALWAYS a list; ``gh`` is ALWAYS resolved to an absolute path via
    ``shutil.which`` -- never ``shell=True``, never a string command.
  - Only an allow-listed set of read-only subcommands can be built. There is no
    code path here that mutates GitHub state -- writes live (disabled/stubbed) in
    agentic/writer.py and are never reachable from this module.
  - No token is ever placed in argv. ``gh`` resolves its own credential from its
    keyring / GH_TOKEN; CyClaw neither reads nor forwards it.

This module does NOT import anything from gate.py, graph.py, or the FastAPI / MCP
layer. It runs strictly out-of-band.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # noqa: S404 -- argv-list gh invocation only; never shell=True

from utils.errors import AgenticError, GhNotInstalledError, GhVersionError
from utils.logger import audit_log

# ---------------------------------------------------------------------------
# Version handling
# ---------------------------------------------------------------------------

DEFAULT_MIN_GH = (2, 40, 0)

# `gh version 2.55.0 (2024-08-21)` -> capture the X.Y.Z triple.
_GH_VERSION_RE = re.compile(r"gh version\s+(\d+)\.(\d+)\.(\d+)", re.IGNORECASE)


def check_gh_version(
    gh_bin: str = "gh",
    min_version: tuple[int, int, int] = DEFAULT_MIN_GH,
) -> tuple[int, int, int]:
    """Confirm ``gh`` is installed and at/above ``min_version``.

    Returns the parsed ``(major, minor, patch)`` tuple. Raises
    ``GhNotInstalledError`` if the binary is not on PATH, or ``GhVersionError``
    if the version is too old or unparseable.
    """
    binary = shutil.which(gh_bin)
    if binary is None:
        raise GhNotInstalledError(
            "GitHub CLI (gh) not found on PATH",
            details={
                "looked_for": gh_bin,
                "install_hint_linux": "see https://github.com/cli/cli#installation",
                "install_hint_windows": "winget install GitHub.cli",
            },
        )

    try:
        result = subprocess.run(  # noqa: S603 -- argv list, absolute binary, no shell
            [binary, "version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GhVersionError(
            f"gh version check timed out: {exc}",
            details={"binary": binary},
        ) from exc

    output = (result.stdout or "") + (result.stderr or "")
    match = _GH_VERSION_RE.search(output)
    if not match:
        raise GhVersionError(
            "Could not parse gh version output",
            details={"binary": binary, "output": output[:500]},
        )

    found = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    if found < min_version:
        raise GhVersionError(
            f"gh {found[0]}.{found[1]}.{found[2]} is too old; need >= "
            f"{min_version[0]}.{min_version[1]}.{min_version[2]}",
            details={
                "found": ".".join(map(str, found)),
                "required": ">=" + ".".join(map(str, min_version)),
                "binary": binary,
            },
        )
    return found


# ---------------------------------------------------------------------------
# Read-only operation catalog
# ---------------------------------------------------------------------------

# Default --json field sets per resource (kept small; callers can override).
_PR_FIELDS = "number,title,state,author,headRefName,baseRefName,isDraft,url,body"
_PR_LIST_FIELDS = "number,title,state,author,isDraft,url"
_ISSUE_FIELDS = "number,title,state,author,labels,url,body"
_ISSUE_LIST_FIELDS = "number,title,state,author,url"
_REPO_FIELDS = "name,owner,description,defaultBranchRef,isPrivate,url"

# Every supported op maps to a builder. There is intentionally NO entry that
# mutates state -- this dict IS the read-only allow-list.
_READ_OPS = frozenset(
    {"pr_view", "pr_list", "pr_diff", "issue_view", "issue_list", "repo_view"}
)


def build_read_argv(
    op: str,
    repo: str,
    *,
    number: int | None = None,
    limit: int = 30,
    gh_bin: str = "gh",
) -> list[str]:
    """Build the argv list for a read-only ``gh`` operation.

    ``op`` must be one of the read-only ops in ``_READ_OPS``; anything else
    raises ``AgenticError`` (no write op can ever be built here). ``repo`` is the
    validated ``owner/name`` slug. ``number`` is required for the *_view / pr_diff
    ops. The returned list always starts with ``gh_bin`` and uses only literal
    flags plus validated inputs -- no shell, no interpolation into a string.
    """
    if op not in _READ_OPS:
        raise AgenticError(
            f"Unknown or non-read-only gh op: {op!r}",
            details={"op": op, "allowed": sorted(_READ_OPS)},
        )

    if op in ("pr_view", "pr_diff", "issue_view") and number is None:
        raise AgenticError(
            f"op {op!r} requires a 'number'",
            details={"op": op},
        )

    num = str(int(number)) if number is not None else None

    if op == "pr_view":
        return [gh_bin, "pr", "view", num, "--repo", repo, "--json", _PR_FIELDS]
    if op == "pr_diff":
        return [gh_bin, "pr", "diff", num, "--repo", repo]
    if op == "pr_list":
        return [gh_bin, "pr", "list", "--repo", repo, "--json", _PR_LIST_FIELDS,
                "--limit", str(int(limit))]
    if op == "issue_view":
        return [gh_bin, "issue", "view", num, "--repo", repo, "--json", _ISSUE_FIELDS]
    if op == "issue_list":
        return [gh_bin, "issue", "list", "--repo", repo, "--json", _ISSUE_LIST_FIELDS,
                "--limit", str(int(limit))]
    # op == "repo_view"
    return [gh_bin, "repo", "view", repo, "--json", _REPO_FIELDS]


def run_read(
    op: str,
    repo: str,
    *,
    number: int | None = None,
    limit: int = 30,
    gh_bin: str = "gh",
    min_version: tuple[int, int, int] = DEFAULT_MIN_GH,
    timeout: int = 30,
) -> dict:
    """Run a read-only ``gh`` op and return a structured result dict.

    Verifies the gh version, resolves the binary to an absolute path, runs it
    (argv list, no shell), and audits the call. ``pr_diff`` returns raw text under
    ``{"diff": ...}``; the JSON ops return ``{"data": <parsed>}``. Raises
    ``AgenticError`` on non-zero exit. Never raises with secret-bearing details.
    """
    found = check_gh_version(gh_bin, min_version)
    binary = shutil.which(gh_bin)
    if binary is None:  # pragma: no cover -- check_gh_version already guards this
        raise GhNotInstalledError("gh disappeared after version check", details={"op": op})

    argv = build_read_argv(op, repo, number=number, limit=limit, gh_bin=binary)

    try:
        completed = subprocess.run(  # noqa: S603 -- argv list, absolute binary, no shell
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        audit_log({"event": "agentic_read_timeout", "op": op, "repo": repo})
        raise AgenticError(
            f"gh {op} timed out after {timeout}s",
            details={"op": op, "repo": repo},
        ) from exc

    audit_log({
        "event": "agentic_read",
        "op": op,
        "repo": repo,
        "number": number,
        "gh_version": ".".join(map(str, found)),
        "exit_code": completed.returncode,
    })

    if completed.returncode != 0:
        # stderr can echo back the (non-secret) request; truncate defensively.
        raise AgenticError(
            f"gh {op} failed with exit code {completed.returncode}",
            details={"op": op, "repo": repo, "stderr": (completed.stderr or "")[:500]},
        )

    if op == "pr_diff":
        return {"op": op, "repo": repo, "diff": completed.stdout}

    try:
        data = json.loads(completed.stdout or "null")
    except json.JSONDecodeError as exc:
        raise AgenticError(
            f"gh {op} returned non-JSON output",
            details={"op": op, "repo": repo, "output": (completed.stdout or "")[:500]},
        ) from exc
    return {"op": op, "repo": repo, "data": data}
