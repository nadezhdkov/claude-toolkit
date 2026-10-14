# Contributing

Thanks for helping! Bug reports, tool ideas and pull requests are welcome.

## Setup

```bash
git clone https://github.com/nadezhdkov/claude-toolkit.git
cd claude-toolkit
uv sync
```

## Before opening a pull request

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest
uvx --from shellcheck-py shellcheck install.sh     # if you changed the installer
```

Or `make ci` for all of it (`make` lists the shortcuts: `lint`, `format`,
`test`, `shellcheck`, `actions`, `screenshots`).

- **Start from a real pain.** New tools need a sentence like "I lost X / got Y
  wrong because this was missing" and a testable done criterion
  (see [docs/design.md](docs/design.md)).
- **Ask before changing the system.** Use `common.confirm()`, support
  `--dry-run`/`--yes`, back up user files, and keep `ctk` stdlib-only.
- **Document it** in `docs/` (commands go in `docs/commands/`). If you change
  `README.md` or `docs/installation.md`, update their translations in
  [docs/i18n](docs/i18n/README.md) too, or ask in the pull request for help with
  a language you don't read; `tests/test_i18n.py` checks that they match.
- **Add a changelog entry** under `## [Unreleased]` in
  [docs/CHANGELOG.md](docs/CHANGELOG.md). CI/docs-only changes can get the
  `skip-changelog` label from a maintainer instead.
- **Don't touch version numbers.** Maintainers run `make release`
  ([docs/releasing.md](docs/releasing.md)); the next version comes from your PR title, so
  `feat:` and `fix:` matter.
- **Title the PR with [Conventional Commits](https://www.conventionalcommits.org/)**,
  e.g. `feat: add ctk audiocheck` or `fix(runq): recognise vitest 4 summary`.

## What CI checks

| Check | Job |
|---|---|
| Ruff lint and format | `CI / Lint` |
| `install.sh` | `CI / Shellcheck` |
| Tests on Python 3.11, 3.12, 3.13 | `CI / Test (Python 3.x)` |
| `uv tool install` and a smoke run of every command | `CI / Install` |
| Conventional Commits PR title | `PR checks / PR title` |
| `docs/CHANGELOG.md` updated | `PR checks / Changelog` |

All of them are required before merging.

## Review and auto-merge

1. A maintainer reviews the pull request.
2. When it is ready, the maintainer adds the **`automerge`** label.
3. GitHub squash-merges it as soon as every required check passes.

If an outside contributor pushes new commits after the label was added,
auto-merge is switched off and the label removed, so every merged change has
been seen by a maintainer. Forked pull requests from first-time contributors
need a maintainer's approval before their workflows run.
