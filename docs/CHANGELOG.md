# Changelog

All notable changes to claude-toolkit are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/nadezhdkov/claude-toolkit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nadezhdkov/claude-toolkit/releases/tag/v0.1.0
