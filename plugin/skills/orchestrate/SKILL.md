---
name: orchestrate
description: When and how to delegate to the ctk subagents (test-runner, reviewer, researcher): briefs, parallel fan-out, the implement-test-review loop. Not for small or sequential edits.
---

# Orchestrate subagents

A subagent starts with an empty context: it costs a brief to start and a
report to read, and it cannot see this conversation. Delegate only when that
cost buys something.

## When to delegate

Delegate when the work is:
- **noisy** — long test/build output, wide reading of code or docs, whose
  details the main conversation does not need (`test-runner`, `researcher`);
- **independent** — questions or checks that do not depend on each other,
  which can run in parallel;
- **a second opinion** — reviewing a change you just wrote (`reviewer`): a
  fresh context does not share your assumptions.

Do it yourself when the task is small, sequential (each step depends on the
last), needs the conversation's context to make sense, or when you would have
to paste most of what you know into the brief anyway.
Never delegate a decision that belongs to the user.

## The agents

| Agent | Give it | You get back (enforced contract) |
|---|---|---|
| `ctk:test-runner` | the command if known, the directory | ≤25 lines: counts, failures with `path:line` and likely cause, log path; `VERDICT: pass/fail/error` |
| `ctk:reviewer` | the base branch or commit range, what the change is meant to do | ≤40 lines: findings with `path:line`, scenario and evidence; `VERDICT: approve/changes-requested/blocked` |
| `ctk:researcher` | one precise question and where to look first | ≤30 lines: answer with a source for every claim; `VERDICT: answered/partial/not-found` |

The `agent-contract` hook sends an agent back once if its report is too long,
lacks a valid `VERDICT:` line, or makes claims without evidence.

## Writing the brief

Each brief is self-contained — the agent knows nothing else:

```
Goal: <what you need and why, in one or two sentences>
Context: <repository/directory, branch or range, relevant files, what was already tried or ruled out>
Constraints: <what not to touch or run; time or scope limits>
Return: <anything beyond the agent's standard contract, e.g. "only failures in tests/api/">
```

One question or one check per agent. Two unrelated questions → two agents.

## Patterns

**Parallel fan-out.** Start independent agents in the same turn (several
Agent calls in one message): e.g. three `researcher`s on three separate
questions, or `test-runner` and `reviewer` together. Usually two to four;
more costs more context than it saves.

**Verify loop after implementing:**
1. Run `ctk:test-runner` and `ctk:reviewer` in parallel on the change.
2. `fail` or `changes-requested`: fix what the evidence supports, then rerun
   only the agent(s) that failed.
3. Stop after three rounds without convergence and report to the user what
   is still failing and why.
4. Done when the verdicts are `pass` and `approve`. Say so with the verdict
   lines, not "looks good".

**Research before deciding.** For a design choice that depends on facts
(library behaviour, how existing code handles a case), send `researcher`s
first, then decide with their evidence in hand.

**Parallel implementation** of truly independent parts only, each in its own
worktree (Agent `isolation: "worktree"`), then review the combined diff. Parts
that touch the same files are not independent.

## Reading the results

- Treat a report as evidence to check, not as truth: open the cited
  `path:line` for anything you will act on, especially a `high` finding or a
  surprising answer.
- `blocked`, `error`, `partial` and `not-found` are results too — decide
  whether to retry with a better brief, do it yourself, or ask the user.
- Relay to the user what matters (verdicts, the findings you acted on); do not
  paste whole reports.
