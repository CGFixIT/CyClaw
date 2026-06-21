# `.claude/` — Project Skills & Workflows

Quick reference for Claude Code assistance patterns in CyClaw.

## Skills

| Skill | Type | Purpose |
|-------|------|--------|
| [`run-cyclaw`](skills/run-cyclaw/SKILL.md) | Operational | Build, run, and smoke-test the FastAPI server |
| [`architecture-refactor`](skills/architecture-refactor/SKILL.md) | Loop | Iterative architecture cleanup |
| [`tests-refactor`](skills/tests-refactor/SKILL.md) | Loop | Test coverage to 100%, pass rate ≥85% |
| [`logging-refactor`](skills/logging-refactor/SKILL.md) | Loop | Logging on every important path, tested logs |
| [`speed-refactor`](skills/speed-refactor/SKILL.md) | Loop | Endpoint latency to <50 ms |
| [`wrap-up`](skills/wrap-up/SKILL.md) | Session | End-of-session checklist (ship, remember, review, publish) |

## Invoking Skills

```bash
/run-cyclaw              # Smoke-test the server
/architecture-refactor   # Start architecture refactor loop
/tests-refactor          # Start test coverage loop
/logging-refactor        # Start logging audit loop
/speed-refactor          # Start speed optimization loop
/wrap-up                 # Run end-of-session checklist
```

## Refactor Loop Pattern

All `*-refactor` skills follow the same seven-step cycle:

1. **Measure** — baseline the current state (tests, latency, log coverage)
2. **Assess** — identify the highest-leverage gap
3. **Execute** — make one focused change
4. **Test** — verify correctness via smoke test or pytest
5. **Commit** — commit with a clear message
6. **Track** — record progress in `/tmp/refactor-CyClaw.md`
7. **Loop** — repeat until all stopping criteria are met

## Folder Structure

```
.claude/
├── README.md              ← this file
├── settings.json          ← project permissions and hooks
├── skills/                ← project-specific skills
│   ├── run-cyclaw/        ← SKILL.md + smoke.sh
│   ├── architecture-refactor/
│   ├── tests-refactor/
│   ├── logging-refactor/
│   ├── speed-refactor/
│   └── wrap-up/
└── rules/                 ← project-specific rules (scoped by paths:)
```

## Key Conventions

- Skill folders: `kebab-case`, matching `name:` in SKILL.md frontmatter
- All SKILL.md files use YAML frontmatter: `name:`, `description:`
- Refactor progress is tracked in `/tmp/refactor-CyClaw.md`
- Git identity must be set before commits: `git config user.email noreply@anthropic.com`
