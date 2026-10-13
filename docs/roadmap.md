# Roadmap

Each phase ends when its done criteria pass and `ctk sessions` has recorded a
measurement. Status: ✅ done · 🚧 in progress · ⏳ planned.

## ✅ Phase 0 — skeleton (0.1.0)

Repository, `install.sh` with dry-run and confirmation, `ctk setup` with
backup and uninstall, CI (lint, shellcheck, tests on 3.11–3.13, install smoke
test, PR title, changelog, label-driven auto-merge).

## ✅ Phase 1 — foundation and measurement (0.1.0)

- `ctk sessions`: baseline metrics before any behavioural change.
- `ctk doctor`: toolchain pins and dependency sync.
- `ctk runq`: failures and summary instead of full output.
- `ctk lsp`: language servers and official LSP plugins.

## 🚧 Phase 2 — automatic quality (Claude Code plugin)

Implemented as the `ctk` plugin ([docs/commands/hooks.md](commands/hooks.md)); the phase
closes after the warn-only week and a `ctk sessions` before/after measurement.

| Hook | Event | Behaviour |
|---|---|---|
| `format-file` | after Edit/Write | format only the edited file with the project's formatter; silent on success |
| `affected-tests` | end of turn | run affected tests through `ctk runq`; speak only on failure |
| `guard-destructive` | before Bash | flag `rm -rf` outside the project, force-push to `main`, `git reset --hard` with uncommitted work. **Starts in warn-only mode** and switches to blocking after a week without false positives |
| `secrets` | before `git commit` (and as a git `pre-commit` hook) | `gitleaks` on the staged changes |
| `notify` | waiting for input / long task done | desktop notification, at most one per minute |

Measured with `ctk sessions`: "file changed on disk" notices must not rise.

## ✅ Phase 3 — verification

- ✅ `ctk shoot` ([docs](commands/shoot.md)): deterministic screenshots (web via Playwright, Godot, headless
  desktop), contact sheets and baseline comparison with tolerance and masks.
- ✅ `ctk audiocheck` ([docs](commands/audiocheck.md)): loudness, peaks/clipping, silence, loop seams, plus
  spectrogram and waveform PNGs.

## ✅ Phase 4 — process skills

`debug`, `ship`, `handoff` (progress file across sessions), `onboard-repo`,
`visual-qa` and `security-pass`, in the `ctk` plugin ([docs/skills.md](skills.md)).

## ✅ Phase 5 — isolation and docs

- ✅ `ctk sandbox` ([docs](commands/sandbox.md)): bubblewrap profile without network, read-only system, only
  the target mounted, CPU/memory/time limits.
- ✅ `ctk libdocs` ([docs](commands/libdocs.md)): installed version, source path, README and types of a
  dependency, to stop writing code against the wrong API version.

## 🚧 Phase 7 — context and evidence

From the context-engineering review, measured with the benchmark and real
transcripts (2.5 billion tokens read in a week, 99% from cache, a median peak
window of 560k tokens, Bash outputs re-read ~390M times over):

- ✅ `benchmark/`: fixed tasks with and without the plugin in Docker.
- ✅ `ctk sessions`: real tokens, peak window, compactions, re-read cost.
- ✅ `ctk map`: budgeted repository map and symbol uses.
- ✅ Always-on context halved (1,570 → 820 tokens), measured by the benchmark.
- ✅ `ctk verify`: evidence ledger of checks per code state.
- ✅ `ctk diffcheck`: deterministic checks of a change.
- ✅ `continuity` hook: verified state after a compaction.
- ⏳ `ctk recall`, only if the measurements show search is still missing (after Phase 8).

## ✅ Phase 6 — subagents

`reviewer`, `researcher` and `test-runner`, each with an output contract
(maximum length, evidence format, final verdict) enforced by the
`agent-contract` hook, plus the `orchestrate` skill ([docs/agents.md](agents.md)).

## ⏳ Phase 8 — session relay ([#21](https://github.com/nadezhdkov/claude-toolkit/issues/21))

Long sessions, not missing context, are now the largest cost. `ctk sessions`
over the week of 2026-10-06 to 10-13: 2.58 billion tokens read, a median peak
window of 505k tokens, and Bash output re-read ~409M times over against ~2M
tokens of original output. Every result stays in the window and is read again
on each later call. The only remedies today are `/clear` or a new terminal, both
by hand and both losing the thread. The goal is to make a fresh session cheap
and safe to start, so the work moves on to it with only what matters.

- ⏳ **Relay point in `ctk sessions`**: per-session growth of the window and of
  the re-read cost, and the size above which a fresh session would have cost
  less. This sets the threshold for the hook below instead of guessing it.
- ⏳ **`continuity` after `/clear`**: also run on `SessionStart` with source
  `clear` (and `resume`), so a fresh session gets the branch, commit,
  uncommitted files, `ctk verify` status and the branch's handoff file. The
  handoff file becomes the memory the two sessions share, and this is the
  fallback when `ctk relay` cannot open a terminal.
- ⏳ **`relay` hook**: when the session's window passes the threshold (read
  from the transcript every hook receives; once per session, configurable),
  ask Claude to stop at the next safe point, with no edit half done, and run
  `ctk relay`.
- ⏳ **`ctk relay`**: Claude first brings the branch's handoff file up to date
  (goal, decisions, next step); the command adds the facts that do not depend
  on it (branch, commit, uncommitted files, `ctk verify` status, as
  `continuity` does), writes them to a file and opens a new terminal (konsole,
  alacritty, kitty, gnome-terminal or a tmux window, detected) running
  `claude --append-system-prompt-file <file>` with "continue from the handoff"
  as its first prompt. The old session then ends its turn and changes nothing
  more, so two sessions never edit the same worktree. Opening a terminal
  changes the system: it asks first, and without a terminal exits 3 unless the
  user opted in once with `[relay] auto = true`. With no terminal found it
  falls back to telling the user to run `/clear`, which `continuity` picks up.
- ⏳ Nudge large Bash output through `ctk runq` (24 `runq` runs for 5,653 Bash
  calls that week), so less enters the window in the first place.

Done when, over a week of real use, the median peak window and the Bash
re-read cost have both fallen by at least half, and the benchmark scores have
not dropped. `ctk recall` (Phase 7) waits for this measurement.
