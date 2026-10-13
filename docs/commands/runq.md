# `ctk runq`

Runs a command, keeps its complete output in a log file and prints only what
matters. Built for agents, whose context window is the scarce resource, and
just as handy for people.

```bash
ctk runq -- <command> [args...]
ctk runq --keep 100 -- npm test     # keep the 100 most recent logs (default 50)
```

## Contract

- The exit code is always the command's exit code (`127` if the command does not exist).
- The complete, unmodified output is written to
  `${XDG_CACHE_HOME:-~/.cache}/claude-toolkit/runq/<timestamp>-<command>.log`.
- Output of up to 60 lines is printed unchanged, followed by a status line.
- Longer output is reduced to:
  1. a header: `runq: exit <code> · <lines> lines · log: <path>`;
  2. the recognised failure lines (at most 50, with a count of the rest);
  3. the tool's own summary lines;
  4. when the command failed but no failure lines were recognised, the last 40 lines.
- ANSI colour codes are stripped from the printed summary (not from the log).

## Recognised tools

The extractor is chosen from the command name first, then from the output
itself (so `make test` that runs pytest is still recognised).

| Tool | Failure lines | Summary |
|---|---|---|
| pytest | `FAILED …` / `ERROR …` from the short summary | `== N failed, M passed in Xs ==` |
| vitest / jest | `FAIL`, `×`, `✗`, `●` lines | `Test Files`, `Tests`, `Test Suites`, `Duration` |
| tsc | `error TS…` | `Found N errors` |
| ruff, eslint, flake8, oxlint, biome | `path:line:col` diagnostics | `Found N errors`, `✖ N problems` |
| cargo | `error[E…]`, `-->` locations, failing tests | `test result:` |
| go test | `--- FAIL`, `file.go:line:`, `panic:` | `ok`/`FAIL` package lines |
| gradle | `FAILED`, compiler errors | `BUILD SUCCESSFUL/FAILED` |
| anything else | lines containing error, fail, panic, exception, traceback, fatal | — |

## Done criteria

- 500 synthetic pytest failures produce fewer than 80 printed lines, an exact
  failure count and the log path; every printed failure is real.
- The exit code always matches the command's.
