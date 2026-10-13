# Hooks (`ctk` plugin) and `ctk hook`

The `ctk` Claude Code plugin, in [`plugin/`](../../plugin), registers five
hooks. Each is a one-line shell command that calls `ctk hook <name>` with the
event JSON on stdin, so all logic lives in the tested `ctk` package.

| Hook | Event | Behaviour |
|---|---|---|
| `format-file` | after Edit/Write | formats only the edited file with the project's formatter; silent on success |
| `affected-tests` | after Edit/Write (records), end of turn (runs) | runs the tests related to this turn's edits; speaks only on failure |
| `guard-destructive` | before Bash | flags `rm -rf` outside the project, force-push to `main`/`master`, `git reset --hard` with uncommitted work; **warn-only by default** |
| `secrets` | before Bash (`git commit`) | `gitleaks` on the staged changes; denies the commit on findings |
| `notify` | waiting for input, end of a long turn | desktop notification, at most one per minute |

## Install

`ctk setup` offers it (asking first). By hand:

```bash
claude plugin marketplace add /path/to/claude-toolkit   # or: nadezhdkov/claude-toolkit
claude plugin install ctk@ctk
```

A marketplace added from a local checkout reads the plugin from that
directory, so `git pull` updates it. Remove it with `ctk setup --uninstall` or
`claude plugin uninstall ctk@ctk`.

## Shared contract

- **Fail-open.** Invalid input, a missing tool or a bug never blocks Claude
  Code: the hook exits `0` and appends the traceback to
  `~/.cache/claude-toolkit/hooks/errors.log`. The plugin's commands end in
  `exit 0`, so a missing or outdated `ctk` is ignored too.
- **Quiet.** Nothing is printed when all is well or when a hook does not apply.
  Only `guard-destructive` (in block mode) and `secrets` can stop a tool call,
  and only `affected-tests` can ask Claude to continue a turn.
- **Per project.** Hooks are installed once, globally, and decide at run time
  whether they apply.

## Configuration

Settings come from `~/.config/claude-toolkit/config.toml`, then from the
nearest `.claude-toolkit.toml` above the working directory (project values win;
`disable` lists are combined).

```toml
[hooks]
disable = ["notify"]            # or `disable = true` to turn every hook off

[hooks.guard-destructive]
mode = "warn"                   # "warn" (default) or "block"
protected-branches = ["main", "master"]

[hooks.affected-tests]
timeout = 240                   # seconds for all test runs at the end of a turn

[hooks.notify]
min-seconds = 60                # notify when a turn took at least this long
```

## `format-file`

Runs after `Edit`, `Write`, `MultiEdit` and `NotebookEdit` on a file inside
the project (the git root, or the working directory), skipping vendored and
build directories. The first formatter that the project configures wins:

| Files | Formatter | Configured when |
|---|---|---|
| `.py`, `.pyi` | `ruff format` | `[tool.ruff]` in `pyproject.toml`, or `ruff.toml` |
| `.py`, `.pyi` | `black` | `[tool.black]` in `pyproject.toml` |
| JS/TS, JSON, CSS | `biome format --write` | `biome.json(c)` and `node_modules/.bin/biome` |
| JS/TS, JSON, CSS, HTML, Markdown, YAML… | `prettier --write` | a Prettier config or `"prettier"` in `package.json`, and `node_modules/.bin/prettier` |
| `.rs` | `rustfmt --edition <Cargo.toml edition>` | a `Cargo.toml` |
| `.go` | `gofmt -w` | a `go.mod` |
| `.lua` | `stylua` | `stylua.toml` |
| C, C++, Objective-C | `clang-format -i` | `.clang-format` |

Python tools come from the project's `.venv` first, then `PATH`; Node tools only
from `node_modules`. If the formatter fails (usually a syntax error), Claude
gets its first lines as context; nothing is blocked.

## `affected-tests`

Edited files are recorded per session. When Claude stops, they are mapped to
tests and run with `ctk runq`'s machinery (full logs in
`~/.cache/claude-toolkit/runq/`):

| Language | Tests | Runner |
|---|---|---|
| Python | edited test files, `test_<module>.py` and `<module>_test.py` anywhere in the project, a `conftest.py`'s directory | pytest from `.venv`, else `uv run --frozen pytest` with `uv.lock` |
| JS/TS | `vitest related --run` or `jest --findRelatedTests` | `node_modules/.bin` |
| Go | `go test` on the edited packages | `go` |

Rust is not covered yet: `cargo test` has no cheap "related tests" mode.

On failure the hook stops Claude from ending the turn and gives it the
failure digest. If the tests still fail when Claude stops again, the user gets
a one-line warning instead, so the hook never loops. Pytest's "no tests
collected" (exit 5) counts as a pass.

## `guard-destructive`

Parses each Bash command (through `&&`, pipes, `sudo`, `env`, `cd dir &&`,
`git -C dir` and `bash -c '…'`) and flags:

- `rm` with recursive **and** force flags on a target that is not strictly
  inside the project or a temporary directory (`/tmp`, `/var/tmp`, `$TMPDIR`,
  the session scratchpad). The project itself, its parents and targets that
  depend on unknown variables are always flagged. When the session runs in
  the home directory or `/`, there is no project to protect, so every such target is flagged.
- `git push` with `-f`, `--force`, `--force-with-lease` or a `+ref` refspec
  to a protected branch (explicit, `HEAD`, or the current branch when no
  refspec is given).
- `git reset --hard` while tracked files have uncommitted changes.

**Warn mode** (default): the command runs, the user sees a warning and the
match is appended to `~/.cache/claude-toolkit/hooks/guard.log`. Review it with
`ctk hook guard-destructive --log`. After a week without false positives, set
`mode = "block"`: the command is then denied and Claude is told to ask the user to run it.

## `secrets`

On a Bash command containing `git commit`, runs `gitleaks` on the staged
changes (and unstaged ones for `commit -a`) with `--redact`, using
`gitleaks git --pre-commit --staged` (8.19+) or `gitleaks protect --staged`.
Findings deny the commit and list `file:line rule` only, never the secret.
The repository's `.gitleaks.toml` and `.gitleaksignore` apply. Without
gitleaks the user is told once per session and commits go through.

The same scan works as a plain git hook, for commits made outside Claude Code:

```bash
printf '#!/bin/sh\nexec ctk hook secrets --git\n' > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

## `notify`

Sends a desktop notification (`notify-send` on Linux, `osascript` on macOS)
when Claude Code needs permission or has been idle waiting for input, and when
a turn that took at least `min-seconds` ends. At most one notification per
minute across all sessions.

## Measurement

Formatting after an edit can make Claude Code report "file changed on disk".
Compare `ctk sessions --since 7` (the `changed on disk` line) before and after
installing the plugin: it must not rise.

## Done criteria (tested in `tests/test_hooks.py`)

- Broken input exits `0` with no output and logs the error; the plugin's
  commands exit `0` even when `ctk hook` fails.
- `.claude-toolkit.toml` can disable a hook or all hooks.
- Guard: a table of safe and destructive commands is classified correctly;
  warn mode only warns and logs; block mode denies.
- Secrets: a staged finding denies the commit without printing the secret;
  missing gitleaks warns once per session.
- Format: only configured formatters run, never on files outside the project;
  failures reach Claude.
- Affected tests: sources map to their tests; failures block once, then only warn;
  passes and turns without edits are silent.
- Notify: short turns are silent, long ones notify, at most once per minute.
