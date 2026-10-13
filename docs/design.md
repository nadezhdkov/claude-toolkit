# Design

## Principles

1. **Measure by real pain.** Each piece enters with a sentence of the form
   "I lost X or got Y wrong because this was missing" and leaves if it is not
   used for 30 days (`ctk sessions --since 30`).
2. **Context is the scarce resource.** Prefer what costs no context until it
   is used: commands on `PATH`, described in one line of `CLAUDE.md`, over MCP
   servers whose tool descriptions are loaded in every session.
3. **Fast, quiet, fail-open.** Tools and hooks say nothing when all is well,
   do nothing when a project does not apply, and degrade with a useful message
   when a dependency is missing. Only safety checks block.
4. **Never change the system without asking.** Every change is planned, shown
   and confirmed; `--dry-run` shows the plan; without a terminal the command
   exits `3` so a person can approve and rerun with `--yes`.
5. **One source of truth, versioned.** Everything lives in this repository;
   `~/.claude` receives a marked, removable section.
6. **The toolkit is software too.** Tests, CI, changelog and semantic versions.

## Output

- **Styled for people, plain for agents.** Colour, bar charts, the overview
  screen and the progress spinner are used only when stdout (or stderr, for the
  spinner) is an interactive terminal. Pipes, logs and Claude Code receive plain
  text, whose format is a stable contract covered by tests.
- `NO_COLOR` always disables colour; `FORCE_COLOR` or `CLICOLOR_FORCE` enable it
  without a terminal; `TERM=dumb` disables it. Truecolor is used when
  `COLORTERM` is `truecolor` or `24bit`, otherwise the 16 basic colours.
- The palette comes from the logo: sky and cyan accents, green for success,
  amber for warnings, red for errors and slate for secondary text.
- Paths under the home directory are shown as `~/…`.
- All styling lives in `style.py`; commands never write escape codes directly.

## Choosing a shape

| Shape | Context cost | Use for |
|---|---|---|
| `ctk` subcommand | none until used | deterministic actions |
| Skill | short description always, body on demand | processes that need judgement |
| Hook | none (runs outside the conversation) | things that must always happen |
| Subagent | description always, isolated execution | noisy or independent work, with an output contract |
| MCP server | every tool description, every session | only real state or protocols |

## Architecture

```
claude-toolkit/
├── src/claude_toolkit/   # the `ctk` CLI (stdlib only)
│   ├── cli.py            # argument parsing and exit codes
│   ├── common.py         # confirmation, host detection, versions, colour
│   ├── doctor.py         # toolchain and dependency checks
│   ├── runq.py           # output capture and failure extraction
│   ├── lsp.py            # language detection and LSP plugin status
│   ├── sessions.py       # transcript metrics
│   ├── setup.py          # Claude Code integration (CLAUDE.md section, plugin)
│   ├── shoot.py          # screenshots, baselines, contact sheets
│   ├── shoot_web.py      # Playwright script run under `uv run --with playwright`
│   ├── png.py            # stdlib PNG reader/writer
│   ├── audiocheck.py     # loudness, clipping, silence, loop seams
│   ├── sandbox.py        # bubblewrap jail with cgroup limits
│   ├── hooks/            # `ctk hook <name>`: logic behind the plugin hooks
│   ├── semver.py         # npm-style ranges
│   └── pep440.py         # Python version specifiers
├── plugin/               # the `ctk` Claude Code plugin: hooks (call `ctk hook`) and skills/
├── .claude-plugin/       # marketplace.json: the repository is a plugin marketplace
├── tests/                # pytest
├── docs/                 # documentation and assets
└── install.sh            # bootstrap installer (POSIX sh)
```

Hooks (and, later, skills and subagents) ship as the **`ctk` Claude Code
plugin** in `plugin/`; the repository doubles as a plugin marketplace, so they
install and update through `claude plugin` and their context cost is visible
with `claude plugin details`. Hooks call `ctk hook <name>` for their logic and
end in `exit 0`, so an outdated or missing `ctk` can never block a tool call.
(Plugin names starting with `claude-` are reserved, hence `ctk`.)

### Hook scope

Hooks are installed once, globally, and decide per project at run time: each
hook detects whether it applies (for example the formatter runs only when the
project configures one) and stays silent otherwise. A project can opt out with
a `.claude-toolkit.toml` file at its root.

## Runtime dependencies

`ctk` uses only the Python standard library (3.11+). External programs
(`node`, `uv`, `ffmpeg`, language servers…) are detected, never required for
the command that does not need them. Python packages a single command needs
(Playwright for `ctk shoot web`) run in an ephemeral, version-pinned
environment through `uv run --with`, never imported by `ctk` itself.
