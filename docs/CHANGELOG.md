# Changelog

All notable changes to claude-toolkit are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `install.ps1`: the Windows installer, with the same plan, questions and
  exit codes as `install.sh`. The plugin's `ctk` launcher finds Python as
  `python3`, `python` or `py -3` and an installed `ctk.exe`, and CI installs
  and smoke-tests `ctk` on macOS and Windows.
- `ctk relay`: hands the work over to a fresh Claude Code session in a new
  terminal window (tmux, konsole, kitty, alacritty, wezterm, ghostty,
  gnome-terminal, foot or xterm, detected or set with `[relay] terminal`),
  starting from the branch's handoff file, which must be fresh. Asks first
  (exit 3 without a terminal unless `[relay] auto = true`), locks the old
  session's edits (`--release` lifts it) and falls back to `/clear`.
- `relay` hook: at the end of a turn whose window passed the relay point
  (`[hooks.relay] threshold`, default 300,000 tokens), asks Claude once per
  session to update the handoff and run `ctk relay`; denies edits in a session
  that has handed over.
- `runq-nudge` hook: after a Bash command that printed more than ~2,000 tokens
  without `ctk`, suggests `ctk runq` or filtering, once per command.
- `ctk sessions` reports the window growth per call and the relay point: the
  window size at which a fresh session would have cost least, and what it
  saves.

### Changed

- Windows and macOS: tests run on both in CI. All text files and command
  output are read and written as UTF-8, `ctk` prints UTF-8 on Windows
  consoles, paths in output use `/` on every system, a confirmation on
  Windows no longer waits for input from `NUL`, and the `guard-destructive`
  hook no longer fails on Windows home paths.
- The `continuity` hook also runs after `/clear`, on resume and at the start
  of a session opened by `ctk relay`.
- `ctk relay` docs: Claude Code's folder trust question, and trusting the
  folder that holds your projects so relayed sessions open without it.
- Roadmap: Phase 7 is closed. `ctk recall` is not built because the
  transcripts show no missing search (5 repeated searches in 1,944, none
  repeated after a compaction); Phase 8 re-checks it.

## [0.3.0] - 2026-10-13

The `ctk` Claude Code plugin (quality hooks, process skills, subagents with
enforced output contracts), verification tools (`shoot`, `audiocheck`),
isolation and dependency docs (`sandbox`, `libdocs`), and context and
evidence tools measured by a new Docker benchmark (`sessions` with real
tokens, `map`, `verify`, `diffcheck`, the `continuity` hook, and a plugin whose
always-on context was halved).

### Added

- `continuity` hook: after a compaction, puts back the branch, commit,
  uncommitted files, the `ctk verify` status of every check (stale ones
  marked) and the branch's handoff file. The `handoff` skill now asks for a
  source and date per fact, struck-through superseded decisions and
  `ctk verify` lines with their commit.
- `ctk diffcheck`: deterministic checks of the current change against a base
  (default: the merge-base with the default branch, uncommitted and untracked
  files included): public symbols removed or with changed signatures and where
  removed ones are still used (high, exit 1), lockfiles, manifests, CI,
  container, environment, generated, large and binary files, debug leftovers
  and TODO comments in added lines, and source changed without tests. The
  `reviewer` agent and the `ship` and `security-pass` skills start from it.
- `ctk verify`: an evidence ledger. Every `ctk runq` run (and every
  `affected-tests` run) inside a git repository is recorded with its exit code,
  counts, log and a hash of the exact code state (HEAD, uncommitted changes,
  untracked files); `ctk verify` shows each check as pass, fail, stale (it ran
  on other code) or never, and exits 1 unless all are fresh and passing.
  `ctk verify run` runs the configured (`[verify] commands`) or detected
  checks. The `ship` skill, the `test-runner` agent and the CLAUDE.md section
  use it.
- `ctk map`: a compact, line-budgeted map of a repository's source files and
  their central symbols (Python via `ast`; JS/TS, Go, Rust, GDScript, Java and
  Kotlin via patterns), ranked by how many files mention a name and how few
  define it, breadth-first across directories, with tests, docs and code-less
  directories summarised. `--uses SYMBOL` lists the definition, the uses and
  the tests that touch it. Used by the `onboard-repo` skill and the
  `researcher` agent.
- `ctk sessions` reports real token usage from the transcripts' usage
  records (fresh input, cache writes, cache reads, output, cache hit rate),
  tokens per session and the peak context window, compactions, repeated reads
  of the same file (counted through a hash, never the name), and "results
  re-read later": each tool output's size times the model calls that read it
  again, by tool. The weekly CSV gains the matching columns.
- `benchmark/`: fixed tasks run with and without the plugin, each in a clean
  Docker container (Claude Code at the host's version, this branch's ctk,
  nothing from the user's configuration), reporting score, context tokens,
  turns and cost per arm. First cases: long test output, an installed API that
  differs from legacy code, and a commit with a staged secret.
- `plugin/bin/ctk`: the plugin ships a launcher, so its skills and agents find
  `ctk` even where `~/.local/bin` is not reachable; an installed `ctk` still
  comes first on `PATH`.
- Subagents in the `ctk` plugin: `test-runner` (haiku), `reviewer` and
  `researcher`, read-only and unable to start other agents, each declaring an
  output contract (maximum lines, allowed verdicts, evidence) in its frontmatter.
- `agent-contract` hook (SubagentStop): sends a ctk subagent's report back once
  when it is too long, lacks a valid `VERDICT:` line or gives a verdict without
  `path:line`/URL evidence.
- `orchestrate` skill: when to delegate, self-contained briefs, parallel
  fan-out and the implement → test → review loop.
- `ctk libdocs`: the installed version of a dependency next to its declared
  constraint, its source path, README sections and public API, for Python,
  Node (with `@types` fallback), Rust and Go; `--find SYMBOL` prints where a
  symbol is defined with its signature and docs; `--readme`, `--api`, `--json`.
  Packages are parsed, never imported or executed.
- `ctk sandbox`: runs a command in a bubblewrap sandbox with no network, the
  system read-only, an empty home (toolchains read-only, credentials never
  mounted), a cleared environment, the target directory read-write (or
  `--read-only`), and memory, CPU and process limits through a systemd user
  scope plus a wall-clock timeout. Defaults follow the machine's RAM (memory:
  half of it, at most 4G; tmpfs `/tmp` and home: an eighth, at most 1G). Project defaults in `[sandbox]` of
  `.claude-toolkit.toml`; `--dry-run` shows the mounts and the command.
- `ctk doctor --toolkit` checks for bubblewrap.
- Process skills in the `ctk` plugin: `debug`, `ship`, `handoff`,
  `onboard-repo`, `visual-qa` and `security-pass` (`/ctk:<name>`), which use
  the `ctk` commands for their deterministic steps and defer to a project's own
  process.
- `ctk shoot`: deterministic screenshots of web pages (Playwright's Chromium,
  run through `uv run --with playwright==1.63.0`), Godot 4 scenes (movie
  writer at a fixed frame rate) and desktop programs (private Xvfb display);
  `--baseline` comparison with threshold, tolerance, masks, bounding box and
  diff image; `ctk shoot compare` and `ctk shoot sheet` (numbered contact
  sheets). Web captures report HTTP, console and page errors.
- A standard-library PNG reader and writer (`png.py`).
- `ctk audiocheck`: integrated loudness, loudness range and true peak (EBU
  R128), clipping (flat tops at the peak value), silent files, leading and
  trailing silence, inner gaps, DC offset and, with `--loop`, clicks and level
  jumps at the loop point; `--target` loudness, `--strict`, `--json` and
  `--images` (waveform and spectrogram PNGs).
- `ctk doctor --toolkit` checks for Xvfb and ffmpeg.
- The `ctk` Claude Code plugin (`plugin/`, with the repository as its
  marketplace) and `ctk hook <name>`, the logic behind its hooks:
  `format-file` (format the edited file with the project's formatter),
  `affected-tests` (run tests related to the turn's edits when Claude stops;
  block once on failure), `guard-destructive` (warn-only by default: `rm -rf`
  outside the project, force-push to protected branches, `git reset --hard`
  over uncommitted work), `secrets` (gitleaks before `git commit`, also usable
  as a git pre-commit hook with `--git`) and `notify` (desktop notifications,
  at most one per minute).
- Per-project hook settings and opt-out in `.claude-toolkit.toml`, user-wide in
  `~/.config/claude-toolkit/config.toml`.
- `ctk setup` offers to register the marketplace and install the plugin;
  `--uninstall` removes them.
- `ctk doctor --toolkit` checks for gitleaks.

### Changed

- The plugin's skill and agent descriptions and the `CLAUDE.md` section are
  about half as long (about 820 always-on tokens instead of 1,570), keeping
  each trigger; `ctk lsp` and `ctk sessions` left the section because people,
  not Claude, run them.
- CI installs bubblewrap and allows unprivileged user namespaces in the
  integration job, so the sandbox tests run there.
- `ctk` loads command modules lazily, roughly halving start-up time (hooks run
  on every tool call).

### Fixed

- `ctk sandbox` now explains a memory-limit kill also when systemd stops the
  scope with SIGTERM (exit 143), not only on the kernel's SIGKILL (137).
- `ctk runq` gave commands started in the same second the same log file, so
  the later one overwrote the earlier log; logs now get a `-2`, `-3`… suffix.
- `ctk libdocs` crashed on an unreadable `package.json` inside `node_modules`.

## [0.2.0] - 2026-10-13

### Added

- Styled terminal output for every command: a branded header, coloured status
  symbols, highlighted failures and test counts, aligned tables, copyable
  install commands and bar charts of tool usage in `ctk sessions`, using a
  truecolor palette from the logo with a 16-colour fallback.
- `ctk` without a command shows an overview of commands and examples.
- Progress spinners with elapsed time while `ctk runq` runs a command and while
  `ctk sessions` reads transcripts (interactive terminals only).
- `ctk runq` reports the command's duration.
- Styled confirmation prompts and plan output in `ctk setup`.
- README screenshots generated from a synthetic demo environment
  (`scripts/make_screenshots.py`, `scripts/render_terminal.py`).

### Changed

- Paths under the home directory are shown as `~/…` in `doctor`, `lsp` and `runq`.
- Colour follows `NO_COLOR`, `FORCE_COLOR`, `CLICOLOR_FORCE` and `TERM=dumb`;
  pipes and agents keep the plain format unchanged.

### Fixed

- `ctk sessions` counted words such as `ctk as` inside commit messages as
  `ctk` commands; only real subcommands are counted now.
- `ctk runq` did not recognise the summary line of `pytest -q`.

## [0.1.0] - 2026-10-13

### Added

- `ctk doctor`: compares `.nvmrc`, `.node-version`, `package.json` engines and
  `packageManager`, `.python-version`, `requires-python`, `go.mod`,
  `rust-toolchain` and `.tool-versions` with installed versions, and checks
  `node_modules` and `uv` environments against their lockfiles;
  `--toolkit` checks the toolkit's own dependencies with distribution-specific
  install commands.
- `ctk runq`: runs a command, logs the full output and prints only failures,
  summary and log path for pytest, vitest/jest, tsc, linters, cargo, go test
  and gradle, with a generic fallback; exit codes are preserved.
- `ctk lsp`: detects project languages and reports or installs (with
  confirmation) language servers and official Claude Code LSP plugins.
- `ctk sessions`: counts-only usage metrics from Claude Code transcripts, with
  weekly CSV output.
- `ctk setup` and `install.sh`: planned, confirmed, reversible integration with
  a marked section in `~/.claude/CLAUDE.md`, backups, `--dry-run`, `--yes` and
  exit code 3 when confirmation is needed without a terminal.
- CI: lint, shellcheck, tests on Python 3.11–3.13, install smoke test,
  Conventional Commits PR titles, changelog check, label-driven auto-merge,
  Dependabot for SHA-pinned Actions.
- Documentation in `docs/` and contribution guides.

[Unreleased]: https://github.com/nadezhdkov/claude-toolkit/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/nadezhdkov/claude-toolkit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/nadezhdkov/claude-toolkit/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/nadezhdkov/claude-toolkit/releases/tag/v0.1.0
