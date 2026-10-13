# `ctk doctor`

Checks that the installed toolchain matches what a project pins, and that its
dependencies are installed from the lockfile. Read-only.

```bash
ctk doctor [path]        # default: current directory
ctk doctor --toolkit     # the toolkit's own dependencies
ctk doctor -v            # also show passing checks
ctk doctor --json        # machine-readable findings
```

Exit code: `1` when there is at least one error, otherwise `0`.

## Project checks

| Source | Checked against | Level on mismatch |
|---|---|---|
| `.nvmrc`, `.node-version` | `node --version` | error if the major version differs, warning if only minor/patch differ |
| `package.json` `engines.node` (npm-style range) | `node --version` | error |
| `package.json` `packageManager` | `npm`/`pnpm`/`yarn`/`bun --version` | warning (fix: `corepack enable`) |
| `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lock(b)` | `node_modules` and the package manager's install marker | error if `node_modules` is missing, warning if the lockfile is newer |
| `.python-version`, `requires-python` (PEP 440) | `.venv/bin/python`, else `python3` | error |
| `uv.lock` | `uv sync --dry-run --offline` | error if `.venv` is missing, warning if it differs |
| `go.mod` `go` directive | `go version` (minimum) | error |
| `rust-toolchain(.toml)` | `rustc --version` when `rustup` is absent | warning |
| `.tool-versions` (asdf/mise) | node, python, go, rust, ruby | warning |

Ranges that cannot be evaluated (for example hyphen ranges) are reported as
warnings instead of being guessed. Aliases such as `lts/*` are not checked.

## Toolkit checks

`--toolkit` verifies Python ≥ 3.11, the required tools (`git`, `uv`, `claude`)
and optional tools used by released commands (`gh`). Each missing tool comes
with an install command for the detected package manager (pacman, apt, dnf,
zypper, brew). Dependencies of unreleased tools (`ffmpeg`, `bwrap`, `Xvfb`,
`gitleaks`) are listed in the code but stay silent until their tool ships, so
`ctk setup` never asks you to install something nothing uses yet.

## Done criteria

- Detects Node 26 against an `.nvmrc` of 24 and a missing `node_modules`.
- Runs in under 2 seconds on real projects.
- No false positives on projects without pins (`ok (no toolchain pins found)`).
