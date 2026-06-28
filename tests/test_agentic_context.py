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
    """Mimic gh_client.run_read's return shapes: diff ops -> {'diff'}, list ops ->
    {'data': [...]}, view ops -> {'data': {...}}."""
    if op == "pr_diff":
        return {"diff": "diff --git a/f b/f\n+x"}
    if op in ("pr_list", "issue_list"):
        return {"data": [{"number": 1}]}
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
    # Shortlists now carry pagination metadata, not a bare list.
    assert bundle["open_prs"]["items"] == [{"number": 1}]
    assert bundle["open_prs"]["count"] == 1
    assert bundle["open_prs"]["has_more"] is False
    assert bundle["open_issues"]["items"] == [{"number": 1}]
    assert [c.args[0] for c in mr.call_args_list] == ["repo_view", "pr_list", "issue_list"]


def test_list_with_more_signals_truncation():
    # When the +1 probe row comes back, has_more is true and items are capped.
    def fake(op, repo, **kwargs):
        limit = kwargs["limit"]  # _list_with_more requests limit+1
        return {"data": [{"number": i} for i in range(limit)]}  # always returns the full limit+1

    with patch.object(context, "run_read", side_effect=fake):
        out = context._list_with_more(_cfg(), "pr_list", limit=10)
    assert out["has_more"] is True
    assert out["count"] == 10 and len(out["items"]) == 10


def test_list_with_more_no_truncation():
    def fake(op, repo, **kwargs):
        return {"data": [{"number": 1}, {"number": 2}]}  # fewer than the limit

    with patch.object(context, "run_read", side_effect=fake):
        out = context._list_with_more(_cfg(), "issue_list", limit=10)
    assert out["has_more"] is False
    assert out["count"] == 2


def test_read_threads_timeout_and_retries_from_cfg():
    captured: dict = {}

    def fake(op, repo, **kwargs):
        captured.update(kwargs)
        return {"data": {"ok": True}}

    cfg = _cfg()
    cfg.gh_timeout_sec = 17
    cfg.gh_retries = 4
    with patch.object(context, "run_read", side_effect=fake):
        context._read(cfg, "repo_view")
    assert captured["timeout"] == 17
    assert captured["retries"] == 4
    assert captured["min_version"] == cfg.gh_min_tuple


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
