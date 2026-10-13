---
name: ship
description: Finish a change as a pull request: checks, diff review, changelog, commit, push, CI. Use when the work is done; a project's own ship process comes first.
---

# Ship a change

**First, look for the project's own process.** If the repository has a ship
or release skill, `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md` or a PR
template that describes how to finish work, follow it and use the steps
below only to fill gaps. Stop at the first failing step and explain it.

## Steps

1. **Branch.** Never commit to the default branch. If the work is on it, move
   it to a new branch (a worktree when the project develops in worktrees) before committing.
2. **Sync.** `git fetch origin` and merge or rebase the base branch as the
   project prefers. On conflicts in code you did not write, stop and ask.
3. **Checks.** Run the project's linter, formatter check, type checker and
   tests, as CI does: `ctk verify run` (configured or detected checks), or
   `ctk runq -- <command>` for others (also recorded). `ctk verify` must show
   every check ✓ for the current code, not `~ stale`; a failure you believe is
   unrelated still gets reported, not hidden.
   For UI changes run the `visual-qa` skill; for audio, `ctk audiocheck`.
4. **Review the diff.** `git status` and `git diff <base>...`:
   - only files this change needs; no debug code, stray logs, commented-out
     code, unrelated reformatting, generated files or secrets;
   - tests cover the new behaviour;
   - docs and examples changed where behaviour changed.
   For changes touching input handling, auth, file paths, shell commands or
   dependencies, run the `security-pass` skill.
5. **Changelog and version.** If the project keeps a changelog, add the entry
   (usually under `## [Unreleased]`). Bump versions only if the project's
   process says this PR should.
6. **Commit.** Stage explicit paths (not `git add -A` blindly), read
   `git diff --staged`, and commit with a Conventional Commit message
   (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`, `chore:`) unless the
   project uses another convention. Add the attribution trailer the session asks for.
7. **Push and open the PR** — only when the user asked for it or the project
   process includes it; pushing is visible to others. `git push -u origin HEAD`, then
   `gh pr create` with:
   - a title in the commit convention;
   - **Summary**: what and why, in a few bullets;
   - **Test plan**: checkboxes for what was run (ticked, as `ctk verify` shows it) and what remains (unticked);
   - links to issues (`Closes #N`) and to stacked PRs.
8. **Watch CI.** `gh pr checks <n> --watch`. On failure, read the log
   (`gh run view --log-failed`), fix with a new commit, push, repeat.
9. **Hand over.** Give the user the PR link and the check status. Never merge,
   approve, add merge labels or mark a draft ready unless the user asks.
   If the session ends with open questions, run the `handoff` skill.
