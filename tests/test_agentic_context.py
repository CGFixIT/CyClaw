"""Tests for agentic.context -- read-only GitHub context fetchers.

No live gh binary required: ``agentic.context.run_read`` is patched, so these
exercise the bundling logic and the ``allowed_read_ops`` guard without touching
the network or subprocess. Covers the module that was previously at 0% coverage
even though ``--cov=agentic`` was on (the package-level number masked it).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agentic import context
from agentic.config import AgenticConfig
from agentic.context import fetch_issue_context, fetch_pr_context, fetch_repo_context
from utils.errors import AgenticError


def _cfg(allowed: list[str] | None = None) -> AgenticConfig:
    """Build an AgenticConfig with an optional restricted allow-list."""
    kwargs: dict = {"repo": "owner/repo", "mode": "read"}
    if allowed is not None:
        kwargs["allowed_read_ops"] = allowed
    return AgenticConfig(**kwargs)


def _fake_run_read(op: str, repo: str, **kwargs):
    """Mimic gh_client.run_read's return shapes: diff ops -> {'diff'}, else {'data'}."""
    if op == "pr_diff":
        return {"diff": "diff --git a/f b/f\n+x"}
    return {"data": {"op": op, "repo": repo, "kwargs": kwargs}}


# --- fetch_pr_context ------------------------------------------------------

def test_fetch_pr_context_includes_diff_by_default():
    with patch.object(context, "run_read", side_effect=_fake_run_read) as mr:
        bundle = fetch_pr_context(_cfg(), 42)
    assert bundle["repo"] == "owner/repo"
    assert bundle["number"] == 42
    assert bundle["pr"]["op"] == "pr_view"
    assert bundle["diff"].startswith("diff --git")
    # Two reads: pr_view then pr_diff.
    ops = [c.args[0] for c in mr.call_args_list]
    assert ops == ["pr_view", "pr_diff"]


def test_fetch_pr_context_without_diff_skips_diff_read():
    with patch.object(context, "run_read", side_effect=_fake_run_read) as mr:
        bundle = fetch_pr_context(_cfg(), 7, include_diff=False)
    assert "diff" not in bundle
    ops = [c.args[0] for c in mr.call_args_list]
    assert ops == ["pr_view"]


def test_fetch_pr_context_guard_rejects_when_pr_view_not_allowed():
    # allow-list without pr_view -> guard raises before any read.
    with patch.object(context, "run_read", side_effect=_fake_run_read) as mr:
        with pytest.raises(AgenticError):
            fetch_pr_context(_cfg(allowed=["repo_view"]), 1)
    mr.assert_not_called()


def test_fetch_pr_context_guard_rejects_when_pr_diff_not_allowed():
    # pr_view allowed but pr_diff not -> pr_view read happens, then diff guard trips.
    with patch.object(context, "run_read", side_effect=_fake_run_read):
        with pytest.raises(AgenticError):
            fetch_pr_context(_cfg(allowed=["pr_view"]), 1)


# --- fetch_issue_context ---------------------------------------------------

def test_fetch_issue_context_bundles_issue():
    with patch.object(context, "run_read", side_effect=_fake_run_read) as mr:
        bundle = fetch_issue_context(_cfg(), 99)
    assert bundle["repo"] == "owner/repo"
    assert bundle["number"] == 99
    assert bundle["issue"]["op"] == "issue_view"
    assert [c.args[0] for c in mr.call_args_list] == ["issue_view"]


def test_fetch_issue_context_guard_rejects_when_not_allowed():
    with patch.object(context, "run_read", side_effect=_fake_run_read) as mr:
        with pytest.raises(AgenticError):
            fetch_issue_context(_cfg(allowed=["repo_view"]), 1)
    mr.assert_not_called()


# --- fetch_repo_context ----------------------------------------------------

def test_fetch_repo_context_includes_lists_when_allowed():
    with patch.object(context, "run_read", side_effect=_fake_run_read) as mr:
        bundle = fetch_repo_context(_cfg())  # default allow-list has pr_list + issue_list
    assert bundle["repo"] == "owner/repo"
    assert bundle["overview"]["op"] == "repo_view"
    assert bundle["open_prs"]["op"] == "pr_list"
    assert bundle["open_issues"]["op"] == "issue_list"
    assert [c.args[0] for c in mr.call_args_list] == ["repo_view", "pr_list", "issue_list"]


def test_fetch_repo_context_omits_lists_when_not_allowed():
    # Only repo_view allow-listed -> no pr_list / issue_list reads.
    with patch.object(context, "run_read", side_effect=_fake_run_read) as mr:
        bundle = fetch_repo_context(_cfg(allowed=["repo_view"]))
    assert "open_prs" not in bundle
    assert "open_issues" not in bundle
    assert [c.args[0] for c in mr.call_args_list] == ["repo_view"]


def test_fetch_repo_context_guard_rejects_when_repo_view_not_allowed():
    with patch.object(context, "run_read", side_effect=_fake_run_read) as mr:
        with pytest.raises(AgenticError):
            fetch_repo_context(_cfg(allowed=["pr_view"]))
    mr.assert_not_called()
