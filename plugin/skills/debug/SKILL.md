---
name: debug
description: Find and prove the root cause of a bug, crash or failing test before changing code, then fix it with a regression test. Use when the cause is not obvious or a first fix failed.
---

# Debug: root cause before fix

Work in this order and do not skip ahead to editing code. A fix without a
proven cause is a guess, and guesses pile up.

## 1. Reproduce

- Write down the exact failing command and the expected vs actual result.
- Run it through `ctk runq -- <command>` so long output stays out of the
  context; the full log path is printed if you need more.
- Make it fail **reliably**. For flaky failures, loop it (`for i in $(seq 20)`)
  and record the failure rate; a fix must bring it to 0 over the same loop.
- Shrink it: the smallest input, test or script that still fails.

## 2. Rule out the environment

- `ctk doctor` — a toolchain that does not match the project's pins, or
  dependencies out of sync with the lockfile, explain many "impossible" failures.
- Does it fail on a clean checkout of the base branch? If not, the cause is in
  the diff: `git diff <base>...` and `git stash` to compare.

## 3. Narrow down

Pick the cheapest technique that halves the search space:

- **Regression with a known good version:** `git bisect start <bad> <good>`
  then `git bisect run <repro command>`.
- **Data or input:** bisect the input (half the file, half the cases).
- **Code path:** read the stack trace from the innermost project frame; use
  go-to-definition (LSP) rather than grep to follow calls. `ctk lsp` tells
  whether the language server is available.
- **State:** add temporary logging at the boundaries (inputs and outputs of
  the suspect function), never everywhere at once.

Keep a short list of hypotheses. For each, write the observation that would
confirm or refute it, then run exactly that check.

## 4. Prove the cause

State the root cause in one sentence that explains **every** symptom,
including why it did not fail before. If one symptom is left unexplained, the
cause is not found yet. Point to the evidence: a log line, a value, a bisect
result, a minimal repro.

## 5. Fix and lock it in

- Fix the cause, not the symptom (no retries, sleeps or broadened excepts that
  hide it).
- Add a regression test that fails without the fix and passes with it; show
  both runs.
- Remove all temporary logging.
- Rerun the original reproduction and the surrounding test suite with
  `ctk runq`.

## Report

```
Cause: <one sentence>
Evidence: <the observation that proves it>
Fix: <what changed, file:line>
Regression test: <name> — failed before, passes now
```

If you stop without a proven cause, say so plainly and list the hypotheses
ruled out and the next check to run.
