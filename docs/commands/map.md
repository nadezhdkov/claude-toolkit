# `ctk map`

A compact map of a repository, so Claude reads a few dozen lines instead of
opening files one by one to find its way.

```bash
ctk map                       # this repository, at most 120 lines
ctk map ~/src/api --budget 60
ctk map --uses build_engine   # where a symbol is defined and used, and which tests touch it
ctk map --json
```

## The map

```
map: ~/src/api · 258 files · 152 source · 383 symbols
src/
  app.js  buildApp(opts = {})
src/config/
  env.js  required(name, { allowEmptyInTest = false } = {}) · optional(name, fallback) · bool(name, fallback)
src/repositories/  (25 more source)
  auditLogs.repo.js  insert(knex, entry) · list(knex, filters = {}) · listAllForExport(knex, filters = {})
test/  (21 tests)
docs/  (6 docs)
(141 less-used source files not shown; --budget 60 shows more)
```

- **Files** come from `git ls-files` (tracked and untracked-but-not-ignored),
  else a walk that skips `node_modules`, virtual environments, build output
  and caches. Binary and very large files are skipped.
- **Symbols**: Python through `ast` (functions with their parameters, classes
  with their public methods); JavaScript/TypeScript, Go, Rust, GDScript, Java
  and Kotlin through line patterns (exported functions, classes, types,
  constants). Names starting with `_` are hidden.
- **Ranking**: a name is central when many files mention it and few define
  it, so fifteen repositories that each define `findById` do not crowd out the
  rest. Files are ranked by their most central symbols (entry points such as
  `main.py`, `cli.py`, `index.ts`, `main.go` get a bonus), and the map is
  breadth-first: the best file of every directory before more files from the
  same one.
- **Budget**: at most `--budget` lines (default 120). Tests, docs and other
  files are counted per directory, and directories without source code are
  rolled up into their top-level directory; what did not fit is counted.

## `--uses SYMBOL`

```
map: execute · 2 definition, 4 source, 2 test
  src/claude_toolkit/runq.py:257  [definition] def execute(
  src/claude_toolkit/hooks/affected_tests.py:210  [source] done = runq.execute(plan.command, cwd=plan.cwd, timeout=remaining)
  tests/test_runq.py:94  [test] first = runq.execute([sys.executable, "-c", "print('one')"])
tests: tests/test_runq.py, tests/test_sandbox.py
```

Definitions first, then uses in source, tests, docs and other files (at most
40 lines). The `tests:` line lists test files that mention the symbol plus,
for Python, the tests `affected-tests` maps to the defining module. Exit `1`
when the symbol is not found.

Nothing is executed or imported; a whole repository takes a fraction of a
second.

## Done criteria (tested in `tests/test_map.py`)

- Source files show their public symbols with signatures; private names are
  hidden; tests, docs and code-less directories are summarised.
- Central files and names come first; the line budget is never exceeded and
  what was hidden is counted.
- `--uses` lists the definition first, then uses, and the tests that touch it.
- Go, Rust and GDScript symbols are recognised; no file is executed.
