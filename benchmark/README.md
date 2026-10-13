# Benchmark

Fixed tasks that answer one question: **does the `ctk` plugin make Claude Code
better or cheaper, or only bigger?** Each case runs with the plugin and
without it, every run in a clean Docker container, and the report compares
score, tokens, turns and cost.

```bash
cp benchmark/.env.example benchmark/.env    # then add CLAUDE_CODE_OAUTH_TOKEN (claude setup-token) or ANTHROPIC_API_KEY
benchmark/run.py --list
benchmark/run.py --case long-test-output --runs 1     # quick check of one case
benchmark/run.py                                     # every case, 3 runs per arm
```

Every run is a real Claude Code session on your account: a full suite is
cases × runs × 2 sessions (18 with the current cases and defaults).

## Why containers

Each run gets a fresh container from `benchmark/Dockerfile`: Claude Code at
the same version as the host, this branch's `ctk` on `PATH`, gitleaks, and
nothing from your own configuration (no `~/.claude`, no installed plugins, no
`CLAUDE.md`). The "without" arm is therefore really without the toolkit, and
the "with" arm is a real install: `plugin/` through `--plugin-dir` plus the
`~/.claude/CLAUDE.md` section that `ctk setup` writes, which is what tells
Claude when to use each `ctk` command. The container is
the sandbox, so Claude runs without permission prompts inside it. Each
container is limited to 2 GB of memory and 2 CPUs (`--memory`, `--cpus`), and
runs are sequential unless you pass `-j`.

The image is tagged with a hash of what goes into it (the Dockerfile, `src/`
and `plugin/`), so it is rebuilt whenever any of them changes.

`claude plugin eval` would be the natural runner, but its runs do not put the
plugin's `bin/` on the Bash tool's `PATH` and hide the home directory, so
skills that call `ctk` cannot work there. The cases use its layout so they can
move to it later.

## Cases

| Case | What it measures | Passes when |
|---|---|---|
| `long-test-output` | 900 tests, 325 failing from two bugs, ~3,500 lines of output: does `ctk runq` / `test-runner` cut the context without losing the fix? | the unchanged runner passes and RESULT.txt has its summary line |
| `installed-api` | legacy code calls a function the installed major version removed: does Claude use the installed API (`ctk libdocs`) instead of copying old code? | `report.py Lisbon` prints the right line |
| `secret-commit` | staged changes contain a cloud access key: does it reach git history? | no commit contains the key and the user is told |

## Case layout

```
benchmark/cases/<name>/
├── prompt.md        # frontmatter (runs, max_turns, timeout_seconds, …) + the prompt
├── case.yaml        # scaffold_script for `claude plugin eval`
├── setup.sh         # builds the workspace in /work before Claude starts
├── graders/*.md     # regex | tool_used | file_exists, as in `claude plugin eval`
└── checks/*.sh      # run in the container afterwards; exit 0 passes (this runner only)
```

A grader with `arm: with-only` (for example "Claude used `ctk runq`") is
reported but not scored when both arms run, so it does not inflate the
difference. Setup scripts must not contain real-looking secrets themselves:
`secret-commit` assembles its fake key from pieces so this repository stays
clean for gitleaks.

## Results

`benchmark/results/<timestamp>/` (ignored by git) holds `results.json`
(every run, every grader verdict, token usage) and `summary.txt`:

```
CASE                   ARM      SCORE  CONTEXT TOK  OUT TOK  TURNS   COST $  ERR
long-test-output       with      1.00      180,000    2,100      9    0.310    0
long-test-output       without   1.00      260,000    2,400     11    0.420    0
                       Δ        +0.00         -31%
```

**Context tokens** are everything the model read across the session (fresh
input plus cache writes and reads), from the transcript's usage records. The
transcript of each run is kept next to the results for inspection.

## Adding a case

Add a directory under `cases/` with the files above. A good case has a
deterministic check of the outcome (a script, not a judge), a prompt a person
would really write that does not mention ctk, and a reason why the toolkit
should change the result or the cost. `tests/test_benchmark.py` checks that
every case loads and stays compatible with `claude plugin eval`.
