---
name: handoff
description: Write or resume a per-branch progress file so unfinished work survives the session. Use when stopping, pausing or resuming earlier work.
argument-hint: "[write|resume]"
---

# Handoff between sessions

The handoff file is the memory of unfinished work: what the goal is, what is
done, what is next and why decisions were made. It replaces re-reading the
whole history.

## Where it lives

1. If the project defines a handoff location (`AGENTS.md`, `CLAUDE.md`, a
   `sessions/` or `docs/` convention), use it.
2. Otherwise use `.claude/handoff/<branch>.md` in the working tree (`/` in
   the branch name becomes `-`). If that file is neither tracked nor ignored,
   add `.claude/handoff/` to `.git/info/exclude` so it stays local and never
   lands in a commit by accident.

## Resume (`/ctk:handoff resume`, or at the start of a session on a branch with a handoff)

1. Read the handoff file for the current branch.
2. Check that it still matches reality: `git log --oneline -10`,
   `git status`, open PRs (`gh pr list --head <branch>`), and the last check
   status. Note anything that changed since it was written.
3. Tell the user in three lines: the goal, where it stands, the next step you
   are about to take. Then continue with that step.

## Write (`/ctk:handoff write`, or before stopping with unfinished work)

Overwrite the file (it is a snapshot, not a log), at most about 60 lines:

```markdown
# <branch> — <one-line goal>

Updated: <YYYY-MM-DD HH:MM> · Commit: <short sha> · PR: <link or none>

## Status
<one paragraph: what works now, what does not>

## Done
- <completed items, with file paths or commits>

## Next
1. <the very next concrete step, with the command or file>
2. ...

## Decisions
- <decision> — <why; what was rejected>
- ~~<an earlier decision>~~ — superseded by <which, when>: keep it struck through, do not delete it

## Open questions
- <for the user, or unknowns to investigate>

## Verify
- <`ctk verify` lines, with the commit they ran on; a result from another commit is history, not proof>

## Gotchas
- <traps found on the way: flaky tests, env quirks, misleading names>
```

After a compaction, the ctk `continuity` hook puts this file back into the
conversation together with the branch, the commit and `ctk verify`, so keep it
current before long tasks.

Rules: every fact has a source (a file, a command, a commit) and a date;
absolute dates (never "tomorrow"), no secrets or tokens, no copied
command output beyond a line or two (link the `ctk runq` log path instead).
If the project tracks the handoff in git, commit it on the same branch.
