# `ctk libdocs`

Shows what a dependency **really is in this project**: the installed version
next to the declared constraint, where its source lives, its README and its
public API, and where a symbol is defined, with signature and docs. It exists
to stop code being written against the API of a different version than the
one installed.

```bash
ctk libdocs requests                    # summary: version, constraint, README sections, API
ctk libdocs fastify ~/src/api           # another project
ctk libdocs pydantic --find BaseModel.model_dump
ctk libdocs @tanstack/react-query --api # the whole public API
ctk libdocs serde --readme              # the README of the installed version
ctk libdocs github.com/spf13/cobra --json
```

## Where it looks

| Ecosystem | Installed copy | Declared in | API from |
|---|---|---|---|
| Python | `.venv`/`venv` site-packages (else the `python3` on `PATH`), `*.dist-info`; import names such as `yaml` map to `PyYAML` | `pyproject.toml` dependencies, optional dependencies and dependency groups | the package's `__init__.py` (or `.pyi`/`-stubs`), respecting `__all__`; README from the package metadata |
| Node | `node_modules/<name>` up the tree | `package.json` dependencies of all kinds | `types`/`typings`/`exports` type declarations, else `@types/<name>` |
| Rust | `Cargo.lock` version, source in `$CARGO_HOME/registry/src` | `Cargo.toml` | `pub` items of `src/lib.rs` |
| Go | `go.mod` version, source in the module cache (`GOMODCACHE`) | `go.mod` | exported funcs, types, vars and consts of the root package |

`--ecosystem` restricts the search to one of them.

## Output

```
libdocs: fastify 5.12.3 (node) · ~/src/api/node_modules/fastify
  declared: fastify@^5.2.0 in ~/src/api/package.json (dependencies)
  summary: Fast and low overhead web framework, for Node.js
  docs: https://fastify.dev/
  readme: ~/src/api/node_modules/fastify/README.md (420 lines; --readme to print)
  sections: Quick start · Install · Example · Core features · …
  api (~/src/api/node_modules/fastify/fastify.d.ts):
    declare namespace fastify
    export type FastifyServerOptions<
    …
```

`--find SYMBOL` (`Class.method` works for Python) prints `file:line` and the
definition: the signature and first docstring paragraph for Python, the
declaration with its leading comment and body (up to 25 lines) for
TypeScript, Rust and Go.

## Safety and speed

Nothing from the package is imported or executed: Python is parsed with
`ast`, the other languages are read as text. A malicious package cannot run
code through `ctk libdocs`, and a large one costs milliseconds.

## Exit codes

`0` when the package was found, `1` when it is not installed for the project.

## Done criteria (tested in `tests/test_libdocs.py`)

- For each ecosystem, a synthetic project reports the installed version, the
  declared constraint, README sections and the public API (private names hidden,
  `__all__` respected, `@types` fallback, test files ignored).
- `--find` returns the definition with signature and documentation, including
  `Class.method` and declarations spanning several lines.
- A package whose `__init__.py` would exit when imported is still described:
  nothing is executed.
