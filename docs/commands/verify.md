# `ctk verify`

An evidence ledger, so "the tests pass" always means **for this code**. A
test that did not run never shows as passed, and an old result never shows as
current.

```bash
ctk verify            # status of every check for the code as it is now
ctk verify run        # run the project's checks, record them, show the status
ctk verify --json
```

```
verify: ~/src/app · 623104e + uncommitted changes
  ✓ pass   .venv/bin/python -m pytest -q     exit 0 · 214 passed, 1 skipped in 6.84s · just now
  ✗ fail   .venv/bin/python -m ruff check .  exit 1 · Found 1 error. · 2m ago
                                             log: ~/.cache/claude-toolkit/runq/20261013-162802-python.log
  ~ stale  npm run test                      exit 0 · 48 passed · ran on commit 9bc3c9e, code changed since · 3h ago
  ? never  go test ./...                     no record for this code
```

## How it works

- **Recording.** Every `ctk runq` run inside a git repository, and every test
  run of the `affected-tests` hook, appends a record: the command, exit code,
  the tool's summary line, duration, log path, the commit and a hash of the
  **code state**: HEAD, the uncommitted diff (staged and unstaged) and the
  untracked, not ignored files. The ledger lives in
  `${XDG_CACHE_HOME:-~/.cache}/claude-toolkit/verify/`, one file per
  repository, the newest 500 records kept. Recording never changes `runq`'s
  output or exit code, and a failure to record is ignored.
- **Status.** For each command, the latest record is compared with the current
  state: `✓ pass` and `✗ fail` when it ran on exactly this code, `~ stale`
  when the code changed since (even by one character, or a new file), and
  `? never` for a check that has no record. Undoing a change makes an earlier
  record fresh again, because it is the same code.
- **Checks.** `[verify] commands = ["…"]` in `.claude-toolkit.toml`, or detected:
  pytest and ruff through the project's `.venv` or `uv run`, `test`/`lint`/
  `typecheck` scripts with npm, pnpm or yarn, `go vet` and `go test`,
  `cargo test`. A malformed configuration file is reported, not ignored.

## Exit codes

`0` when every listed check is fresh and passing; `1` otherwise, or outside a
git repository, or when there is nothing to check.

## Done criteria (tested in `tests/test_verify.py`)

- A `runq` run is recorded and shows as pass; editing a file makes it stale;
  undoing the edit makes it fresh again; a new untracked file makes it stale.
- Failures show the summary and the log path, and the command exits 1.
- Configured checks without a record show as never; `verify run` runs and records them.
- Detection covers Python (`.venv`), pnpm scripts and Go.
- Nothing is recorded outside a git repository; a broken configuration is reported.
