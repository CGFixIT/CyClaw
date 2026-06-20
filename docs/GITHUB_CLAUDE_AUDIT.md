# `.github/` & Claude Code Permissions / Auth Audit

**Scope:** All files under `.github/` (workflows, dependabot, issue templates,
SECURITY.md) plus Claude Code integration points (`.github/workflows/claude.yml`,
`.claude/`). This document is **advisory** — it lists findings and recommended
remedies. Auth-sensitive changes (the `@claude` action) are written as proposals
rather than applied, because changing them can break the live integration.

Severity legend: 🔴 high · 🟡 medium · 🟢 low / informational

---

## 1. 🔴 `claude.yml` runs an unpinned `@beta` action with write scopes

`.github/workflows/claude.yml:29`

```yaml
uses: anthropics/claude-code-action@beta
```

The action is invoked at the **mutable `@beta` tag** while holding:

```yaml
permissions:
  contents: write
  pull-requests: write
  issues: write
  id-token: write
```

Whatever `@beta` points to at trigger time runs with write access to repo
contents, PRs, and issues. A regression or compromise upstream executes with
those scopes. The `if:` guard (`comment.user.login == 'CGFixIT'`) is a good
authz control and should stay, but it does not mitigate supply-chain risk in
the action itself.

**Remedy**
- Pin to a released tag or commit SHA, e.g. `anthropics/claude-code-action@v1`
  (or a full SHA with a `# vX.Y.Z` comment, matching the style already used for
  `actions/checkout` in `ci.yml`).
- Drop `id-token: write` unless OIDC cloud auth is actually used — it is not
  referenced anywhere in the step and widens the token's blast radius.
- Keep `contents: write` / `pull-requests: write` (Claude needs them to push and
  comment); `issues: write` is only needed if Claude edits issues — drop if not.

---

## 2. 🟡 Inconsistent GitHub Action pinning across workflows

Same actions are SHA-pinned in some workflows and floating-tagged in others:

| Action | Pinned (good) | Floating tag (drift risk) |
|--------|---------------|---------------------------|
| `actions/checkout` | `@34e1148…# v4` (ci, pip-audit) | `@v6` (codeql), `@v4` (others) |
| `actions/setup-python` | `@a26af69…# v5` (ci, pip-audit) | `@v6` (codeql) |
| `actions/upload-artifact` | `@ea165f8…# v4` (ci) | `@v7` (codeql/defender) |
| `github/codeql-action/*` | — | `@v4` |
| `microsoft/*`, `fortify/*` | — | `@v1`, `@v3` |

Two problems: (a) third-party actions on floating tags are a supply-chain
surface GitHub's hardening guide recommends SHA-pinning; (b) the **same** action
runs at different major versions across files (checkout v4 vs v6, upload-artifact
v4 vs v7), so behavior is not uniform.

**Remedy** — SHA-pin all third-party `uses:` with a trailing `# vX.Y.Z` comment
(the convention already established in `ci.yml`), and align major versions.
Dependabot's `github-actions` ecosystem (already configured) will keep the pins
fresh via grouped weekly PRs.

---

## 3. 🟡 No committed `.claude/settings.json` — recurring git-identity friction

`.claude/` ships skills but **no `settings.json`**. The session that produced
`CLAUDE.md` repeatedly tripped the `~/.claude/stop-hook-git-check.sh` hook
because the repo had no committed git-identity defaults, so commits were authored
with the wrong email and flagged "Unverified."

**Remedy** — commit a project-level `.claude/settings.json` that:
- declares a `SessionStart` hook setting `git config user.email noreply@anthropic.com`
  and `user.name Claude`, removing the recurring failure at its source;
- carries a minimal permission allowlist for the read-only commands used every
  session (`git status`, `git log`, `git diff`, `git fetch`) to cut prompt noise.

(This dovetails with the local↔remote sync-guard proposal tracked separately.)

---

## 4. 🟢 `codeql.yml` "manual build" step is a latent `exit 1`

`.github/workflows/codeql.yml:61-66`

```yaml
- name: Run manual build steps
  if: matrix.build-mode == 'manual'
  run: |
    echo "Replace this with your build commands..."
    exit 1
```

Harmless today (the Python matrix entry uses `build-mode: none`, so the step is
skipped), but if anyone adds a `build-mode: manual` language entry the workflow
fails by design until edited. Leave a comment making that explicit, or remove the
scaffold step.

---

## 5. 🟢 Dead-weight / externally-gated workflows

- `defender-for-devops.yml` (MSDO) and `fortify.yml` depend on external service
  credentials (Azure DevOps / Fortify FoD). In recent PR runs **Fortify-AST-Scan
  showed `skipped`** while MSDO ran — confirm Fortify is intentionally gated and
  not silently dead. If the integration isn't wired up, the workflow is consuming
  scheduling overhead for no signal; remove or document it.
- `package.json` is acknowledged as "unused scaffolding" in `dependabot.yml`, yet
  the `npm` ecosystem is still enabled (with two ignores). Consider dropping the
  npm ecosystem block entirely until a real JS app exists, rather than maintaining
  ignore entries for phantom dependencies.

---

## 6. 🟢 Missing governance files

- **No `CODEOWNERS`** — reviews are not auto-requested. A one-line
  `* @CGFixIT` (or finer-grained) file would enforce review routing.
- **No PR template** — the existing PRs are well-structured by convention only.
  A `.github/pull_request_template.md` would standardize Summary / Test plan.
- Issue templates (bug_report, feature_request) and `SECURITY.md` are present and
  in good shape — no action.

---

## Priority order

1. **#1** — pin `claude-code-action`, trim its token scopes (auth blast radius).
2. **#3** — commit `.claude/settings.json` (kills the recurring identity failure).
3. **#2** — SHA-pin + version-align all actions (supply-chain hygiene).
4. **#4 / #5 / #6** — low-risk cleanups when convenient.

Items #1–#3 are the security-meaningful ones; the rest are hygiene.
