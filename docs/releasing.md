# Releasing

Versions follow [Semantic Versioning](https://semver.org/) and are computed, not
chosen: the PR titles (Conventional Commits) say what the next version is, and
`scripts/release.py` writes it into every file at once.

```bash
make version      # current version, last tag, the next version and the commits that decide it
make release      # open the release pull request (asks first)
```

## How the next version is chosen

From the commits since the last `vX.Y.Z` tag, merge commits and `chore: release`
commits left out:

| Commit | Bump |
|---|---|
| `feat:` | minor |
| `fix:`, `perf:`, `revert:` | patch |
| `!` after the type (`feat!:`) or a `BREAKING CHANGE:` footer | major, or **minor while the major version is 0** |
| `docs:`, `chore:`, `ci:`, `test:`, `refactor:`, `style:`, `build:` | none by themselves |

The strongest one wins. With none of them there is nothing to release.

## What a release changes

`make release` needs `gh` and a checkout at `origin/main`. It adds a worktree
`../<repo>-release-<version>` (the maintainer's checkout stays untouched), and in it:

- the version in `pyproject.toml`, `src/claude_toolkit/__init__.py`, `uv.lock` and
  `plugin/.claude-plugin/plugin.json`;
- `docs/CHANGELOG.md`: the `[Unreleased]` entries move under `## [X.Y.Z] - date`, a new empty
  `[Unreleased]` stays on top and the compare links are updated (a release with an
  empty `[Unreleased]` is refused: write the entries first, as every pull request must);
- the overview screenshot, which shows the version;
- one commit `chore: release X.Y.Z`, pushed on `release/X.Y.Z`, and the pull request.

Nothing is written unless all of it can be: a refused release leaves every file as it was.

Review the pull request like any other and add the `automerge` label.

## What merging does

`.github/workflows/release.yml` runs on every push to `main`. When the version in the
files has no tag yet, it tags that commit `vX.Y.Z` and publishes the GitHub release with the
changelog section as its notes. Otherwise it does nothing. It also fails when the version files
disagree, and `tests/test_release.py` checks the same on every pull request, so a hand-edited
version cannot reach `main` unnoticed.

## Fully automatic release pull request (optional)

`.github/workflows/release-pr.yml` keeps a `release/next` pull request up to date on every push
to `main`, the way `make release` would. It needs a `RELEASE_TOKEN` secret: a personal access
token of a maintainer with *contents* and *pull requests* write access to this repository. A
token is needed because the repository does not let `GITHUB_TOKEN` open pull requests, and the
checks would not run on one that did. Without the secret the job only prints a notice.

It never merges: a person still adds the `automerge` label.

## Choosing a version by hand

```bash
python3 scripts/release.py prepare --version 1.0.0   # to cut 1.0.0, or any version newer than the current one
python3 scripts/release.py check                     # do the files agree?
python3 scripts/release.py notes 0.4.0               # the release notes of a version
```
