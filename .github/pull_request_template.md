## What does this change?

<!-- One or two sentences. Link the issue if there is one: Fixes #123 -->

## Checklist

- [ ] PR title follows [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`…)
- [ ] Entry added under `[Unreleased]` in `docs/CHANGELOG.md` (or the change is CI/docs-only)
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run pytest` pass locally
- [ ] Commands that change the system still ask first and support `--yes` / `--dry-run`
- [ ] New tool or hook has a testable done criterion and docs in `docs/`
