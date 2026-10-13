# Changelog

All notable changes to claude-toolkit are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

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

- CI installs bubblewrap and allows unprivileged user namespaces in the
  integration job, so the sandbox tests run there.


- `ctk` loads command modules lazily, roughly halving start-up time (hooks run
  on every tool call).

### Fixed

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

[Unreleased]: https://github.com/nadezhdkov/claude-toolkit/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/nadezhdkov/claude-toolkit/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/nadezhdkov/claude-toolkit/releases/tag/v0.1.0
