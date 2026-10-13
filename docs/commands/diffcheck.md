# `ctk diffcheck`

Deterministic checks of a change, with no model and no network, so a review
(by a person or the `reviewer` agent) starts from facts and spends its
attention on what needs judgement.

```bash
ctk diffcheck                 # against the merge-base with the default branch
ctk diffcheck --base HEAD     # only uncommitted changes
ctk diffcheck --strict        # exit 1 on any finding, not only high ones
ctk diffcheck --json
```

```
diffcheck: 3 file(s) changed, 41 line(s) added since 1a2b3c4d5e6f · 1 high · 3 warn · 1 info
  high  [api] app/engine.py:4  removed `build_engine` is still used in 1 file(s): app/cli.py:1
  warn  [api] app/engine.py:2  signature changed: start(speed) → start(speed, *, warm)
  warn  [debug] app/cli.py:9  debugger left in: breakpoint()
  warn  [dependencies] package-lock.json  lockfile changed: check what was added or upgraded
  info  [tests] app/engine.py  its tests were not changed: tests/test_engine.py
```

The change is the working tree against the base: committed, staged,
unstaged and untracked (not ignored) files.

## Checks

| Kind | Finds | Level |
|---|---|---|
| `api` | public symbols (as `ctk map` extracts them) removed, and where removed ones are still used in source or tests | high when still used, else warn |
| `api` | a public symbol's signature changed | warn |
| `dependencies` | lockfiles (`package-lock.json`, `uv.lock`, `Cargo.lock`, `go.sum`…) and manifests (`pyproject.toml`, `package.json`, `go.mod`…; `setup.py` only at the root) | warn |
| `config` | CI workflows, Dockerfiles, compose files, Makefiles, `.env*`, keys | high for a real `.env`, else warn |
| `generated`, `binary`, `large` | minified/generated files, binaries, files over 512 KiB | warn |
| `debug` | in **added** lines: `breakpoint()`, `pdb`, debug-shaped `print`s (`f"{x=}"`, `print("debug…")`, `repr()`), a printed bare variable in library code (not in command-line programs), `console.log`, `debugger`, `dbg!` | warn |
| `debug` | new `TODO`, `FIXME`, `XXX`, `HACK` comments | info |
| `tests` | source changed with no test change at all | warn |
| `tests` | a Python module changed while the tests `affected-tests` maps to it did not | info |

Printing in command-line programs and in tests is normal output, so those
rules skip it; the patterns favour few false positives over catching every
leftover.

## Exit codes

`0` without high findings (with `--strict`: without any finding), `1`
otherwise, outside a git repository or with an unknown base.

## Done criteria (tested in `tests/test_diffcheck.py`)

- A clean tree has nothing to flag; a removed function still in use is high
  and fails; a signature change is reported.
- Debug leftovers are found only in added lines, and a CLI's normal output is
  not flagged.
- Lockfiles, `.env`, CI files and source without tests are reported.
