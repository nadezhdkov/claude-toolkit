# AGENTS.md

Guidance for AI agents (and people) working on **claude-toolkit**: the `ctk`
CLI plus, in later phases, a Claude Code plugin with hooks, skills and
subagents. User documentation is in [README.md](README.md) and [docs/](docs/);
the design rationale is in [docs/design.md](docs/design.md) and the plan in
[docs/roadmap.md](docs/roadmap.md).

## Commands

```bash
uv sync                                               # dev environment
uv run ruff check . && uv run ruff format --check .   # lint + format (CI runs both)
uv run pytest                                         # tests (CI: Python 3.11-3.13)
shellcheck install.sh                                 # or: uvx --from shellcheck-py shellcheck install.sh
uv run ctk <command>                                  # run the CLI from the checkout
make ci                                               # all of the above (`make` lists the targets)
```

## Rules that must not regress

- **Develop in a separate worktree.** The maintainer's `ctk` is an editable
  install of the main checkout, so half-finished edits there break the command
  they use every day. Work in `git worktree add ../claude-toolkit-dev -b <branch> main`
  and let changes reach the main checkout only through merged pull requests.
- **Styled for people, plain for agents.** Use `style.Style` for all colour and
  decoration; with colour disabled, output must stay byte-for-byte the plain
  format the tests expect. Regenerate README screenshots with
  `uv run python scripts/make_screenshots.py` (synthetic data only).

- **Stdlib only at runtime.** `ctk` must start fast and never break because of
  a third-party package. Dev tools (pytest, ruff) live in the `dev` group.
- **Never change the system without asking.** Anything that writes outside the
  repository or the cache goes through `common.confirm()`: support `--dry-run`
  and `--yes`; without a terminal, raise `ConfirmationRequired` so the CLI exits
  `3` and changes nothing. Back up user files before editing them.
- **Quiet and fail-open.** Print nothing extra on success; when a dependency or
  project file is missing, skip with a useful message instead of crashing.
- **Privacy in `sessions`.** Extract counts and names only; never copy message
  text, file contents or command output. Keep the test that asserts this.
- **Exit codes are contracts.** `runq` returns the wrapped command's code;
  `doctor` and `lsp` return 1 when something is wrong; confirmation needed is 3.
- **Every tool has a testable done criterion** (see `docs/commands/*.md`) and
  a test that checks it.

## Conventions

- Python 3.11+, type hints, `from __future__ import annotations`, dataclasses.
- One module per command in `src/claude_toolkit/`; wire it in `cli.py`.
- Documentation in English, which is the source of truth. `README.md` and
  `docs/installation.md` are translated in `docs/i18n/<language>/`: when you
  change either, update the four translations in the same pull request
  (`tests/test_i18n.py` fails until their structure matches; code blocks stay
  in English). New docs go in `docs/` (commands in
  `docs/commands/`); only standard files (`README.md`, `AGENTS.md`,
  `CLAUDE.md`, `CONTRIBUTING.md`, `LICENSE`, `Makefile`) live at the root.
- Every behavioural change adds an entry under `## [Unreleased]` in
  `docs/CHANGELOG.md` in the same pull request. Semantic Versioning, computed
  from the Conventional Commit titles: never edit a version by hand. `make release`
  writes it into every file and cuts the changelog ([docs/releasing.md](docs/releasing.md));
  merging that pull request tags and publishes the release.
- Commit messages and PR titles follow Conventional Commits.
- GitHub Actions: pin actions by commit SHA, set permissions per job, never
  check out PR code in `pull_request_target`; audit with
  `uvx zizmor --offline .github/workflows/` and `uvx --from actionlint-py actionlint`.

## Merging

Pull requests must pass `Lint`, `Shellcheck`, `Test (Python 3.11|3.12|3.13)`,
`Install`, `PR title` and `Changelog`. A maintainer adds the `automerge` label
and GitHub squash-merges once checks pass; new commits from outside
contributors revoke the label.
