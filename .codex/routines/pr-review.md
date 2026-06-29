# PR Review Routine

## When To Use

Use this for reviewing a pull request, local diff, or proposed patch.

## Inputs To Ask For

- PR number/URL or diff range.
- Review focus: correctness, security, CI, tests, dependency drift, or docs.
- Whether to leave a GitHub comment or report in chat.

## Workflow

1. Read `AGENTS.md`.
2. Inspect changed files and understand the PR goal.
3. For dependency/CI changes, compare `pyproject.toml`, `requirements.txt`, `constraints.txt`, and `Dockerfile`.
4. Look first for bugs, regressions, security issues, missing tests, and CI gaps.
5. Verify claims against code and tests; avoid style-only findings unless they block maintainability.
6. If commenting on GitHub, use the connector PR comment/review tools when
   permissions allow; if they return permission errors, report the blocker
   rather than retrying with unrelated tools.

## Verification Checklist

- Findings are actionable and grounded in file/line references where possible.
- Security invariants considered.
- Tests and CI impact considered.
- No unrequested edits made during review-only work.

## Expected Final Response

- Findings first, ordered by severity.
- Open questions or assumptions.
- Brief summary of reviewed scope.
- Tests/checks inspected, run, or explicitly not run.
