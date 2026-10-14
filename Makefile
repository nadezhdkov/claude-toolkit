# Shortcuts for the commands in AGENTS.md and CONTRIBUTING.md. `make` lists them.
# Needs make and uv; on Windows use the uv commands directly (or make from Git for Windows/MSYS2).

.DEFAULT_GOAL := help

.PHONY: help
help: ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-12s %s\n", $$1, $$2}'

.PHONY: sync
sync: ## install the dev environment (uv sync)
	uv sync

.PHONY: lint
lint: ## ruff lint and format check, as CI runs them
	uv run ruff check .
	uv run ruff format --check .

.PHONY: format
format: ## fix lint findings that ruff can fix, and format
	uv run ruff check --fix .
	uv run ruff format .

.PHONY: test
test: ## run the tests (ARGS="-k relay" to pass pytest options)
	uv run pytest $(ARGS)

.PHONY: check
check: lint test ## lint, format check and tests

.PHONY: shellcheck
shellcheck: ## check the shell scripts
	uvx --from shellcheck-py shellcheck install.sh plugin/bin/ctk benchmark/cases/*/setup.sh benchmark/cases/*/checks/*.sh

.PHONY: actions
actions: ## audit the GitHub Actions workflows
	uvx zizmor --offline .github/workflows/
	uvx --from actionlint-py actionlint

.PHONY: ci
ci: check shellcheck actions ## everything the required CI checks run, locally

.PHONY: screenshots
screenshots: ## regenerate the README screenshots (synthetic data)
	uv run python scripts/make_screenshots.py

.PHONY: install
install: ## run the installer (asks before each step)
	./install.sh

.PHONY: version
version: ## the version, what the commits since the last tag would release, and why
	@python3 scripts/release.py status

.PHONY: changelog
changelog: ## preview what the next release will list: [Unreleased] plus the fragments in docs/changelog.d
	@python3 scripts/release.py changelog

.PHONY: release
release: ## open the release pull request: next version, version files and changelog (asks first)
	python3 scripts/release.py pr

.PHONY: skills
skills: ## regenerate .agents/skills from plugin/skills and .claude/skills
	python3 scripts/sync_agent_skills.py
