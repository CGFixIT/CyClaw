# Proposal: Proactive Local ↔ Remote Sync Guard

**Problem.** Across recent sessions, local `main` repeatedly drifted from
`origin/main`: commits authored with the wrong identity (flagged "Unverified"),
local `main` left ahead/behind after PRs merged remotely, and `git reset --hard`
reached for to reconcile — a destructive operation that can silently discard
unpushed work. The throughline: **nothing proactively surfaces divergence, and
reconciliation is ad-hoc.**

**Goal.** Make divergence *visible at session start* and keep reconciliation
*explicit and human-driven* — never auto-destroy local commits.

---

## Mechanism

A `SessionStart` hook (`.claude/hooks/session-start-sync-check.sh`, included in
this PR but **inert until wired**) that, on every session start:

1. **Pins commit identity** repo-locally to `noreply@anthropic.com` / `Claude`
   — eliminates the recurring "Unverified" stop-hook failure at its source.
2. **Fetches** the default branch (read-only) and **reports** ahead/behind
   counts for the current branch vs `origin/<default>`.
3. If local `main` has diverged, **prints guidance** (ff-only when safe; review
   `log origin/main..HEAD` before discarding) — but **performs no reset, rebase,
   push, or delete.** Exit code is always 0 so it can never block a session.

The hook is deliberately advisory. The human decides how to reconcile; the tool
only removes the "I didn't realize it had drifted" failure mode.

---

## How to enable (opt-in)

The hook script is committed but does nothing until referenced from
`.claude/settings.json`. Create or merge this into that file:

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "bash .claude/hooks/session-start-sync-check.sh" }
        ]
      }
    ]
  },
  "permissions": {
    "allow": [
      "Bash(git status:*)", "Bash(git log:*)", "Bash(git diff:*)",
      "Bash(git fetch:*)",  "Bash(git rev-parse:*)", "Bash(git rev-list:*)",
      "Bash(git branch:*)", "Bash(git show:*)"
    ]
  }
}
```

> Shipping an active `settings.json` is intentionally **left to the human**: it
> registers an auto-running hook and grants standing permissions, which should be
> a deliberate opt-in rather than something a PR turns on silently. The two
> halves (read-only allowlist + advisory hook) are both non-destructive.

---

## Operating conventions (apply with or without the hook)

These are the behavioral rules the hook reinforces; they hold regardless:

1. **Default branch is read-mostly locally.** Don't commit to local `main`; work
   on `claude/<topic>` branches and let PRs land changes on `origin/main`.
2. **After a remote merge, fast-forward — don't reset.**
   `git fetch origin main && git merge --ff-only origin/main`. If ff-only fails,
   *inspect* before reconciling.
3. **`git reset --hard` is a last resort, never reflexive.** Before discarding,
   run `git log origin/main..HEAD` and confirm every local-only commit is either
   already represented upstream or genuinely disposable (e.g. preserve it on a
   throwaway branch first — exactly how the Codacy work was saved this session).
4. **Identity is pinned per-repo,** so new commits are verifiable by default.

---

## Why not auto-sync?

An auto `reset --hard origin/main` at session start would "fix" divergence but is
exactly the destructive act that risks losing unpushed work (this session had
real local-only commits that such a reset would have erased). Surfacing +
guidance is the safer equilibrium: zero data-loss risk, full human control, and
the drift is no longer invisible.
