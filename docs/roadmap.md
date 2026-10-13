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

## 🚧 Phase 5 — isolation and docs

- ✅ `ctk sandbox` ([docs](commands/sandbox.md)): bubblewrap profile without network, read-only system, only
  the target mounted, CPU/memory/time limits.
- `ctk libdocs`: installed version, source path, README and types of a
  dependency, to stop writing code against the wrong API version.

## ⏳ Phase 6 — subagents

`reviewer`, `researcher` and `test-runner`, each with an output contract
(maximum length, evidence format, final verdict).
