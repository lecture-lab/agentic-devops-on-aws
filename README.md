# Agentic DevOps on AWS

Build cloud infrastructure with AI agents without giving up human control.

## Lifecycle

Request
→ Plan
→ Build
→ Validate
→ Approve
→ Deploy
→ Observe
→ Analyze
→ Alert

## Principles

1. Plan before action.
2. Validate before apply.
3. Human approval for high-risk changes.
4. Every deployment must be observable.
5. Every lab must have an exit.

## How this repository grows with the course

You do not get a new project for every section. This one repository grows with you:

```
empty project
→ IaC
→ AWS architecture
→ deployment
→ monitoring
→ alerting
```

## Getting started

```
bash scripts/check-tools.sh
```

See `docs/prompts/` for the exact prompts used in each section — copy them
and run them yourself.

## One-time setup for contributors

```
bash scripts/bootstrap.sh
```

This runs `git config core.hooksPath .githooks` and the scanner's self-test,
which activates the secret-scan pre-commit hook (`scripts/secret-scan.py
--staged`). Git config isn't copied by `git clone`, so this is needed once per
clone -- there's no CI running it automatically yet.

**Known gap, not yet resolved:** an earlier draft of the secret scanner
briefly committed a fixture file containing secret-*shaped* (fake, not
real) strings. `scripts/secret-scan.py --full` (history-inclusive audit
mode) will keep flagging that commit until history itself is rewritten,
which hasn't happened yet -- it's a deliberate action, not something to
do casually on a shared repo. Resolve this before the repo is ever
distributed to students.
