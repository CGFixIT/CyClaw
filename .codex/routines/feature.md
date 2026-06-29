# Feature Routine

## When To Use

Use this for new behavior, an endpoint, CLI capability, workflow enhancement, or user-visible functionality.

## Inputs To Ask For

- User story or desired behavior.
- Target interface: API, MCP, CLI, UI, sync, agentic, guardrails, CI, or docs.
- Security boundaries and rollout expectations.

## Workflow

1. Read `AGENTS.md`, then inspect the owning subsystem.
2. Check existing patterns before designing anything new.
3. Verify whether the feature touches CyClaw invariants, optional layers, or secrets.
4. Prefer a narrow implementation that composes with current modules.
5. Add tests for behavior, validation, and failure modes.
6. Update docs only where users or future agents need the change.
7. Run targeted tests, Ruff, and broader CI parity for cross-cutting work.
8. Keep optional layers optional; do not make `sync/`, `agentic/`, or
   `guardrails/` required by the core gateway unless explicitly requested.

## Verification Checklist

- Existing patterns reused where practical.
- Core gateway/graph/MCP isolation preserved.
- New config defaults are safe and offline-first.
- Tests cover success and refusal/error behavior.
- Docs mention any new setup or runtime command.

## Expected Final Response

- What feature was added.
- How it fits the existing architecture.
- Tests/checks run.
- Approval-limited checks or external services not exercised.
- Any deployment or security notes.
