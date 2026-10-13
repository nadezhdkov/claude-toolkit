---
name: issue
description: Turn an idea, a bug, a roadmap item or follow-up work from a pull request into a GitHub issue for claude-toolkit. Use when the user asks to open, file or track an issue, or when a PR leaves work for later.
argument-hint: "[idea or PR number]"
---

# Open an issue for claude-toolkit

An issue is a plan another person (or a later session) can pick up without
this conversation. It must stand on its own: the problem, evidence from the
code, a proposal and a testable done criterion.

## Steps

1. **Ask before publishing.** Opening an issue is public. Do it only when the
   user asked for it or agreed to it in this conversation.
2. **Look for duplicates.** `gh issue list --state all --search "<keywords>"`.
   If one exists, offer to comment on it instead of opening a new one.
3. **Gather evidence from the code, not from memory.** Use `ctk map --uses NAME`
   and `grep` to find where the behaviour lives, and cite `path:line` or a
   function name. For metrics, run `ctk sessions` and give the numbers with
   their date range. For a PR follow-up, link the PR and the review comment.
4. **Pick the shape.**
   - Bug: follow `.github/ISSUE_TEMPLATE/bug_report.yml` (command, what
     happened, environment). Label `bug`.
   - Tool, hook, skill or subagent idea: follow `tool_idea.yml` (the real
     problem, the shape, how we would know it works). Label `idea`.
   - Larger change or roadmap phase: a tracking issue with a checklist, linked
     to `docs/roadmap.md`. Labels `enhancement` (plus `idea` if not yet
     decided).
   Use only labels that exist (`gh label list`); do not create new ones
   without asking.
5. **Write the body in English** (the project's documentation language), with
   these sections:
   - `## Problem`: what goes wrong or is missing, with evidence.
   - `## Proposal` (or `## Plan` with `- [ ]` items): concrete steps, checked
     against the rules in `AGENTS.md` (stdlib only at runtime, confirmation
     for system changes, fail-open, exit codes).
   - `## Done when`: criteria a test or a command can check, as each
     `docs/commands/*.md` does.
   Write it to the scratchpad and pass it with `--body-file`, never inline.
6. **Create it.** `gh issue create --title "<title>" --label <label> --body-file <file>`.
   The title says what changes, in plain words, without a Conventional Commits
   prefix (that is for PR titles).
7. **Connect it.** If a roadmap item or a PR covers it, mention the issue
   number there (in the PR body as `Closes #N` when the PR finishes it).
8. **Tell the user** the issue URL in one line per issue.

## Several ideas at once

One issue per independent piece of work, so each can be closed by its own
pull request. Group only what must ship together; link related issues to each
other.
