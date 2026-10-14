# `ctk relay`

Hands the work over to a fresh Claude Code session in a new terminal window,
so a session that grew too large stops re-reading its whole window on every
call. The new session starts from the branch's handoff file and from facts
that do not depend on it (branch, commit, uncommitted files, `ctk verify`
status), which the [`continuity`](hooks.md#continuity) hook adds.

```bash
ctk relay              # asks, then opens the new session (exit 3 without a terminal)
ctk relay --dry-run    # show the command and change nothing
ctk relay --show       # what the new session starts from
ctk relay --release    # let a relayed session edit again
```

Normally Claude runs it, asked by the [`relay`](hooks.md#relay) hook when the
window passes the relay point:

1. Claude brings `.claude/handoff/<branch>.md` up to date (`/ctk:handoff write`):
   goal, decisions, next step. `ctk relay` refuses a handoff file older than
   30 minutes (`--force` skips this), because the new session starts from it.
2. `ctk relay` opens a new window in the repository root running
   `claude --name "relay <branch>" [--effort <same>] "<continue from the handoff>"`.
   That session's `continuity` hook (on `SessionStart`, recognised by
   `CTK_RELAY=1` in its environment) puts back the verified state and the
   handoff file.
3. The old session is locked: the `relay` hook denies its edits, so two
   sessions never edit the same worktree. Claude ends its turn there.
4. With `close-old = true`, the old window closes when that turn ends, so only
   the new one stays open (see [Closing the old window](#closing-the-old-window)).

```text
relay: open a new konsole window in /home/me/project running:
  konsole --workdir /home/me/project -e claude --name 'relay feat/x' --effort high 'Continue the work handed over by …'
```

## Terminal

The terminal Claude Code runs in, recognised from its environment: tmux
(`TMUX`), konsole, kitty, alacritty, wezterm, ghostty, gnome-terminal, iTerm2
and Terminal (`TERM_PROGRAM`) or Windows Terminal (`WT_SESSION`). Otherwise
the system's usual one: on Linux the first installed of konsole, alacritty,
kitty, gnome-terminal, wezterm, ghostty, foot and xterm, when a display is
available; on macOS Terminal; on Windows Windows Terminal, else a new
PowerShell console.

Terminal, iTerm2 and Windows Terminal start the new session from their own
process, so it does not inherit the environment: the command sets `CTK_RELAY`
itself (`env …` in a shell on macOS, a PowerShell `-EncodedCommand` on
Windows). macOS asks once to allow automation of Terminal or iTerm2. If none is found, or the
terminal fails to start, nothing is locked and Claude asks the user to type
`/clear`: `continuity` also runs after `/clear`, so the same session continues
from the handoff with an empty window.

## Folder trust

Claude Code asks whether you trust a folder the first time it opens there, and
the new session waits on that question until someone answers it. Trust in a
folder covers everything below it, so trusting the folder that holds your
projects (for example `~/Documents/projects`, by starting `claude` there once)
also covers every repository and worktree inside it. Do not trust `/tmp` or
another directory that other users can write to: a trusted folder runs the
hooks and settings of any project created inside it without asking.

## Configuration

`[relay]` in `~/.config/claude-toolkit/config.toml` or the project's
`.claude-toolkit.toml` (project values win):

```toml
[relay]
auto = true                          # open without asking (default false: asks, exit 3 without a terminal)
terminal = "alacritty"               # a known name, or a custom prefix:
# terminal = ["foot", "-D", "{cwd}"] # the claude command is appended; {cwd} is the repository root
claude-args = ["--model", "opus"]    # extra arguments for the new claude
close-old = true                     # close the old window when its last turn ends (default false)
```

## Closing the old window

With `close-old = true`, `ctk relay` records which process to hang up: the
shell that runs the old `claude` (its window or tab closes when the shell
exits, in every terminal and in tmux), or `claude` itself when the terminal
runs it directly, as a relay starts it. When the old session's turn ends, the
`relay` hook sends that process `SIGHUP` a second later, once, and only if
the pid still belongs to the same program. Other windows and tabs of the
terminal stay open. The old conversation is not lost: `claude --resume` opens
it again. Linux and macOS only; on Windows the old window stays open.

The variables Claude Code sets for its own session (`CLAUDECODE`,
`CLAUDE_CODE_SESSION_ID`, …) are removed from the new session's environment.

## Exit codes

`0` when the new session opened (or with `--dry-run`, `--show`,
`--release`), `1` when it could not (no repository, no fresh handoff, no
terminal, the terminal failed), `3` when it needs approval and no terminal is
attached.

## Done criteria (tested in `tests/test_relay.py`)

- Without a git repository, a handoff file or a fresh one, nothing opens.
- Without a terminal attached it prints the plan and exits 3; `--dry-run`
  opens nothing; `[relay] auto = true` needs no approval.
- With approval it opens the detected terminal in the repository root, without
  the old session's variables, and locks the old session; `--release` unlocks
  it. A terminal that fails at once is reported and locks nothing.
- With no terminal found it falls back to `/clear`.
- `close-old` is off by default; when on, the end of the old session's turn
  hangs up the shell running `claude` (else `claude`), once, and never a
  process whose pid was reused.
