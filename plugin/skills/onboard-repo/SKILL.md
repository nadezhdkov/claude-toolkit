---
name: onboard-repo
description: Get oriented in an unfamiliar repository before changing it — environment and language servers, how to build, test and lint, the layout and entry points, the project's rules, and a baseline test run. Use at the start of work in a repo you have not seen in this session, or when the user asks how a project is organised.
---

# Onboard a repository

Goal: in a few minutes, know how to build, test and change this project
safely, and say so in a short brief. Read; do not edit anything during onboarding.

## 1. Rules first

Read whichever exist: `AGENTS.md`, `CLAUDE.md` (and files it imports with
`@`), `CONTRIBUTING.md`, `README.md`, `.claude/rules/`, the PR template.
Note hard rules (branching, worktrees, commit style, forbidden actions).

## 2. Environment

- `ctk doctor .` — toolchain pins vs installed versions, dependencies vs lockfile.
- `ctk lsp .` — languages, and whether their language servers are ready.
  Prefer go-to-definition and references over grep once they are.

## 3. Commands

Find the real build, test, lint and run commands — in this order of trust:
CI workflows (`.github/workflows/`, `.gitlab-ci.yml`), then task runners
(`Makefile`, `justfile`, `package.json` scripts, `pyproject.toml`,
`Taskfile.yml`, project scripts), then the README. CI is what must pass.

## 4. Layout

Start from `ctk map` (files and their central symbols, within a line budget)
and open only what it points to. Then note:

- Top-level directories and what each holds (one line each).
- Entry points (main modules, servers, CLI, scenes) and the main data flow.
- Where tests live and how they map to source.
- Generated or vendored directories that must not be edited.
Use `ctk map --uses NAME` to find where something is handled instead of reading files in turn.

## 5. Baseline

Run the test suite (or the fastest meaningful subset) through
`ctk runq -- <command>` and record the result. Failures that exist before you
change anything are important context — never "fix" them silently.

## 6. Brief

Reply with at most ~25 lines:

```
Project: <what it is, stack>
Rules: <the ones that constrain how to work>
Commands: build `…` · test `…` · lint `…` · run `…`
Environment: <ctk doctor / ctk lsp findings, or "ok">
Layout: <key directories and entry points>
Baseline: <N passed / M failed (pre-existing: …)>
Unknowns: <what still needs an answer>
```

If the project has no `AGENTS.md`/`CLAUDE.md` and the user wants one, offer
to write it from this brief — but ask first; it is a change to their repository.
