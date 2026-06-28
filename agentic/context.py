"""Higher-level read-only GitHub *context* fetchers for human/agent consumption.

Thin, audit-friendly wrappers over ``agentic.gh_client.run_read`` that assemble
structured context bundles (a PR plus its diff, an issue, a repo overview). These
are pure reads -- nothing here mutates GitHub state, and the module is never
imported by the request path.

Each underlying ``run_read`` call already emits its own audit event, so these
wrappers do not double-log; they only shape the returned data.
"""

from __future__ import annotations

from agentic.config import AgenticConfig
from agentic.gh_client import DEFAULT_MIN_GH, run_read
from utils.errors import AgenticError

_DEFAULT_LIST_LIMIT = 10


def _guard_read_op(cfg: AgenticConfig, op: str) -> None:
    """Reject ops the operator has not allow-listed in config.allowed_read_ops."""
    if op not in cfg.allowed_read_ops:
        raise AgenticError(
            f"read op {op!r} is not in agentic.allowed_read_ops",
            details={"op": op, "allowed": list(cfg.allowed_read_ops)},
        )


def _read(cfg: AgenticConfig, op: str, **kwargs: object) -> dict:
    """``run_read`` with the repo, version floor, and resilience knobs from cfg.

    Centralises threading ``gh_timeout_sec`` / ``gh_retries`` (and ``gh_min_tuple``)
    into every read so the fetchers stay declarative and a config change applies
    uniformly. ``getattr`` defaults keep this safe for an older AgenticConfig built
    without the resilience fields.
    """
    return run_read(
        op,
        cfg.repo,
        min_version=cfg.gh_min_tuple,
        timeout=getattr(cfg, "gh_timeout_sec", 30),
        retries=getattr(cfg, "gh_retries", 0),
        **kwargs,  # type: ignore[arg-type]
    )


def _list_with_more(cfg: AgenticConfig, op: str, limit: int = _DEFAULT_LIST_LIMIT) -> dict:
    """Fetch a capped list plus a ``has_more`` signal.

    Requests ``limit + 1`` rows: if the extra row comes back, more exist beyond
    the cap, so the caller knows the shortlist is partial. Returns
    ``{"items": [...], "count": N, "has_more": bool}`` (items trimmed to ``limit``).
    """
    data = _read(cfg, op, limit=limit + 1)["data"]
    items = data if isinstance(data, list) else []
    has_more = len(items) > limit
    trimmed = items[:limit]
    return {"items": trimmed, "count": len(trimmed), "has_more": has_more}


def fetch_pr_context(cfg: AgenticConfig, number: int, *, include_diff: bool = True) -> dict:
    """Return a PR's metadata and (optionally) its diff as one bundle."""
    _guard_read_op(cfg, "pr_view")
    bundle: dict = {"repo": cfg.repo, "number": number}
    bundle["pr"] = _read(cfg, "pr_view", number=number)["data"]
    if include_diff:
        _guard_read_op(cfg, "pr_diff")
        bundle["diff"] = _read(cfg, "pr_diff", number=number)["diff"]
    return bundle


def fetch_issue_context(cfg: AgenticConfig, number: int) -> dict:
    """Return an issue's metadata bundle."""
    _guard_read_op(cfg, "issue_view")
    return {
        "repo": cfg.repo,
        "number": number,
        "issue": _read(cfg, "issue_view", number=number)["data"],
    }


def fetch_repo_context(cfg: AgenticConfig) -> dict:
    """Return a repo overview plus a shortlist of open PRs and issues.

    The PR/issue shortlists are returned as ``{"items", "count", "has_more"}`` so
    a consumer can tell a complete list from a truncated one (``has_more=true``
    means there are more open items than the shortlist shows).
    """
    _guard_read_op(cfg, "repo_view")
    bundle: dict = {"repo": cfg.repo}
    bundle["overview"] = _read(cfg, "repo_view")["data"]
    if "pr_list" in cfg.allowed_read_ops:
        bundle["open_prs"] = _list_with_more(cfg, "pr_list")
    if "issue_list" in cfg.allowed_read_ops:
        bundle["open_issues"] = _list_with_more(cfg, "issue_list")
    return bundle


__all__ = [
    "DEFAULT_MIN_GH",
    "fetch_pr_context",
    "fetch_issue_context",
    "fetch_repo_context",
]
