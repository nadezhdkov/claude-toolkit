# Changelog

All notable changes to claude-toolkit are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
