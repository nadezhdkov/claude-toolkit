"""``ctk relay``: hand the work over to a fresh Claude Code session in a new terminal.

A long session re-reads its whole window on every model call. A relay moves
the work to a new session that starts from what matters: the branch's handoff
file (written by Claude just before) and the facts that do not depend on it
(branch, commit, uncommitted files, ``ctk verify`` status), which the
``continuity`` hook adds when the new session starts.

The new session runs ``claude`` in a new terminal window (konsole, alacritty,
kitty, gnome-terminal, wezterm, ghostty, foot, xterm or a tmux window),
detected from the environment or set with ``[relay] terminal``. Opening a
window changes the system, so it asks first; without a terminal it exits 3
unless ``[relay] auto = true``. Once the new session is open, the old one is
locked: the ``relay`` hook denies its edits, so two sessions never edit the
same worktree. With ``[relay] close-old = true`` its window also closes when
its turn ends (Linux and macOS), so only the new one stays open.
"""

from __future__ import annotations

import base64
import os
import platform
import shlex
import shutil
import signal
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .common import confirm
from .hooks.base import State, _read_toml, config_home, find_project_config
from .hooks.continuity import handoff_file

HANDOFF_MAX_AGE = 30 * 60  # the handoff must have been written for this relay, not for an earlier one
FIRST_PROMPT = (
    "Continue the work handed over by the previous session (ctk relay). "
    "If no ctk continuity note is in your context, run `ctk relay --show` first."
)
# Set by the running Claude Code session; a child `claude` must not inherit them.
SESSION_ENV = (
    "CLAUDECODE",
    "CLAUDE_PID",
    "CLAUDE_EFFORT",
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
    "CTK_RELAY",
    "CTK_RELAY_FROM",
)


def _prefix(*parts: str) -> Callable[[str, list[str], dict[str, str]], list[str]]:
    """A terminal that runs ``command`` itself and inherits the environment: ``{cwd}`` is replaced."""
    return lambda cwd, command, _env: [part.replace("{cwd}", cwd) for part in parts] + command


def _shell_line(cwd: str, command: list[str], env: dict[str, str]) -> str:
    assignments = [f"{key}={shlex.quote(value)}" for key, value in env.items()]
    return f"cd {shlex.quote(cwd)} && " + shlex.join(["env", *assignments, *command] if assignments else command)


def _applescript(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _powershell(cwd: str, command: list[str], env: dict[str, str]) -> list[str]:
    """PowerShell running ``command`` in ``cwd`` with ``env``, as -EncodedCommand: nothing to escape for wt or cmd."""

    def quote(text: str) -> str:
        return "'" + text.replace("'", "''") + "'"

    lines = [f"$env:{key} = {quote(value)}" for key, value in env.items()]
    lines += [f"Set-Location -LiteralPath {quote(cwd)}", "& " + " ".join(quote(part) for part in command)]
    encoded = base64.b64encode("\n".join(lines).encode("utf-16-le")).decode("ascii")
    return ["powershell", "-NoLogo", "-NoProfile", "-EncodedCommand", encoded]


# name -> (binary that must be installed, argv for the working directory, the command and the relay variables).
# Terminals opened by another process (macOS apps, Windows Terminal) do not inherit our environment, so
# those carry the variables in the command line.
TERMINALS: dict[str, tuple[str, Callable[[str, list[str], dict[str, str]], list[str]]]] = {
    "tmux": ("tmux", _prefix("tmux", "new-window", "-c", "{cwd}", "-n", "relay", "--")),
    "konsole": ("konsole", _prefix("konsole", "--workdir", "{cwd}", "-e")),
    "kitty": ("kitty", _prefix("kitty", "--directory", "{cwd}", "--")),
    "alacritty": ("alacritty", _prefix("alacritty", "--working-directory", "{cwd}", "-e")),
    "wezterm": ("wezterm", _prefix("wezterm", "start", "--cwd", "{cwd}", "--")),
    "ghostty": ("ghostty", _prefix("ghostty", "--working-directory={cwd}", "-e")),
    "gnome-terminal": ("gnome-terminal", _prefix("gnome-terminal", "--working-directory={cwd}", "--")),
    "foot": ("foot", _prefix("foot", "-D", "{cwd}")),
    "xterm": ("xterm", _prefix("xterm", "-e")),
    "terminal": (  # macOS Terminal.app
        "osascript",
        lambda cwd, command, env: [
            "osascript",
            "-e",
            f'tell application "Terminal" to do script {_applescript(_shell_line(cwd, command, env))}',
            "-e",
            'tell application "Terminal" to activate',
        ],
    ),
    "iterm": (
        "osascript",
        lambda cwd, command, env: [
            "osascript",
            "-e",
            'tell application "iTerm" to create window with default profile command '
            + _applescript("/bin/sh -c " + shlex.quote(_shell_line(cwd, command, env))),
        ],
    ),
    "wt": ("wt", lambda cwd, command, env: ["wt", "-d", cwd, *_powershell(cwd, command, env)]),
    "console": ("powershell", lambda cwd, command, env: _powershell(cwd, command, env)),  # a new Windows console
}
# The terminal Claude Code itself runs in, recognised by its environment: (name, variable, value or any).
MARKERS: tuple[tuple[str, str, str | None], ...] = (
    ("tmux", "TMUX", None),
    ("konsole", "KONSOLE_VERSION", None),
    ("kitty", "KITTY_WINDOW_ID", None),
    ("alacritty", "ALACRITTY_WINDOW_ID", None),
    ("alacritty", "ALACRITTY_SOCKET", None),
    ("wezterm", "WEZTERM_PANE", None),
    ("ghostty", "GHOSTTY_RESOURCES_DIR", None),
    ("gnome-terminal", "GNOME_TERMINAL_SCREEN", None),
    ("iterm", "TERM_PROGRAM", "iTerm.app"),
    ("terminal", "TERM_PROGRAM", "Apple_Terminal"),
    ("wt", "WT_SESSION", None),
)
FALLBACK_ORDER = {
    "Linux": ("konsole", "alacritty", "kitty", "gnome-terminal", "wezterm", "ghostty", "foot", "xterm"),
    "Darwin": ("terminal",),
    "Windows": ("wt", "console"),
}

# --- Configuration ---------------------------------------------------------------


def relay_config(cwd: Path) -> dict[str, Any]:
    """``[relay]`` from the user config, then the project's ``.claude-toolkit.toml`` (project wins)."""
    config: dict[str, Any] = {}
    for path in (config_home() / "config.toml", find_project_config(cwd)):
        if path is not None:
            table = _read_toml(path).get("relay")
            if isinstance(table, dict):
                config.update(table)
    return config


# --- Terminal and command ----------------------------------------------------------


def detect_terminal(
    env: Mapping[str, str], which: Callable[[str], str | None] | None = None, system: str | None = None
) -> str | None:
    """The terminal Claude Code runs in, else the system's usual one (Linux: the first installed, with a display)."""
    which = which or shutil.which
    system = system or platform.system()
    for name, variable, value in MARKERS:
        if env.get(variable) and (value is None or env[variable] == value) and which(TERMINALS[name][0]):
            return name
    if env.get("TERM") == "foot" and which("foot"):
        return "foot"
    if system == "Linux" and not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        return None
    return next((name for name in FALLBACK_ORDER.get(system, ()) if which(TERMINALS[name][0])), None)


def claude_command(branch: str, env: Mapping[str, str], extra: list[str]) -> list[str]:
    command = ["claude", "--name", f"relay {branch}"]
    if env.get("CLAUDE_EFFORT"):
        command += ["--effort", env["CLAUDE_EFFORT"]]
    return [*command, *extra, FIRST_PROMPT]


def relay_env(from_session: str | None) -> dict[str, str]:
    """What tells the new session's continuity hook that it was opened by a relay."""
    return {"CTK_RELAY": "1", **({"CTK_RELAY_FROM": from_session} if from_session else {})}


def terminal_command(
    terminal: str | list[str], cwd: Path, command: list[str], env: dict[str, str] | None = None
) -> list[str] | None:
    """A known terminal's name, or a custom prefix (``{cwd}`` is replaced), followed by ``command``."""
    if isinstance(terminal, list):
        return [str(part).replace("{cwd}", str(cwd)) for part in terminal] + command
    known = TERMINALS.get(terminal)
    return known[1](str(cwd), command, env or {}) if known else None


def child_env(env: Mapping[str, str], from_session: str | None) -> dict[str, str]:
    child = {key: value for key, value in env.items() if key not in SESSION_ENV}
    return {**child, **relay_env(from_session)}


# --- Lock of the old session ----------------------------------------------------------


def lock(session_id: str, terminal: str, close: tuple[int, str] | None = None) -> None:
    state = State(session_id, "relay")
    data = state.load()
    data.update({"relayed_at": time.time(), "terminal": terminal})
    if close:
        data["close"] = list(close)
    state.save(data)


def locked(session_id: str) -> bool:
    return bool(State(session_id, "relay").load().get("relayed_at"))


def release(session_id: str) -> None:
    state = State(session_id, "relay")
    data = state.load()
    data.pop("relayed_at", None)
    data.pop("close", None)
    state.save(data)


# --- Closing the old window ----------------------------------------------------------

SHELLS = {"bash", "zsh", "fish", "sh", "dash", "ksh", "mksh", "tcsh", "csh", "nu", "elvish", "xonsh"}


def _process(pid: int) -> tuple[int, str] | None:
    """(parent pid, command name) of a process, from /proc or ps; None if it is gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        name = stat[stat.index("(") + 1 : stat.rindex(")")]
        return int(stat[stat.rindex(")") + 2 :].split()[1]), name
    except (OSError, ValueError, IndexError):
        pass
    try:
        done = subprocess.run(
            ["ps", "-o", "ppid=", "-o", "comm=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            encoding="utf-8",
        )
        ppid, name = done.stdout.split(None, 1)
        return int(ppid), Path(name.strip()).name
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def close_target(env: Mapping[str, str], process: Callable[[int], tuple[int, str] | None] = _process):
    """What to hang up so the old window closes: (pid, name) of the shell that runs claude, else claude itself.

    A shell that exits closes its window or tab in every terminal; a claude run directly by the
    terminal (as a relay starts it) closes the window when it exits. None on Windows or when unknown.
    """
    if os.name == "nt" or not env.get("CLAUDE_PID", "").isdigit():
        return None
    claude = int(env["CLAUDE_PID"])
    info = process(claude)
    if info is None or not info[1].startswith("claude"):
        return None
    parent = process(info[0]) if info[0] > 1 else None
    if parent and parent[1].lstrip("-") in SHELLS:
        return info[0], parent[1]
    return claude, info[1]


def close_later(pid: int, name: str, delay: float = 1.0) -> bool:
    """Hang up ``pid`` after ``delay`` from a detached process, if it is still ``name`` (pids are reused)."""
    current = _process(pid)
    if os.name == "nt" or current is None or current[1] != name:
        return False
    try:
        subprocess.Popen(
            ["sh", "-c", f"sleep {delay}; kill -{int(signal.SIGHUP)} {pid}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    return True


# --- Command -------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _launch(command: list[str], cwd: Path, env: dict[str, str], new_console: bool = False) -> str | None:
    """Start the terminal detached; an error message if it could not start or failed at once."""
    # Windows: a new console window for `console`; elsewhere a new session, so it outlives this one.
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if new_console else 0
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
            creationflags=flags,
        )
    except OSError as error:
        return str(error)
    try:
        code = process.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        return None  # still running: the window is open
    return f"{command[0]} exited with {code}" if code else None


def run(args) -> int:
    from .hooks.continuity import summary
    from .verify import repo_root

    env = dict(os.environ)
    session = args.session or env.get("CLAUDE_CODE_SESSION_ID")
    if args.release:
        if not session:
            print("relay: no session to release (pass --session ID)")
            return 1
        release(session)
        print(f"relay: session {session} may edit again")
        return 0
    root = repo_root(Path.cwd())
    if root is None:
        print("relay: not a git repository. Ask the user to type /clear instead.")
        return 1
    if args.show:
        print(summary(root, "relay") or "relay: nothing to report for this repository")
        return 0

    branch = _git(root, "branch", "--show-current") or "HEAD"
    handoff = handoff_file(root, branch)
    if not args.force:
        if handoff is None:
            name = branch.replace("/", "-")
            print(f"relay: no handoff file for {branch}. Write .claude/handoff/{name}.md first (/ctk:handoff write).")
            return 1
        age = time.time() - handoff.stat().st_mtime
        if age > HANDOFF_MAX_AGE:
            print(
                f"relay: {handoff.relative_to(root)} was written {age / 60:.0f} minutes ago. "
                "Bring it up to date first (/ctk:handoff write): the new session starts from it."
            )
            return 1

    config = relay_config(root)
    terminal = args.terminal or config.get("terminal") or detect_terminal(env)
    if not terminal:
        print(
            "relay: no terminal found to open a new session in. Ask the user to type /clear: "
            "the continuity hook then brings back the branch state and the handoff file."
        )
        return 1
    extra = config.get("claude-args", [])
    extra = [str(part) for part in extra] if isinstance(extra, list) else []
    command = terminal_command(terminal, root, claude_command(branch, env, extra), relay_env(session))
    if command is None:
        print(f"relay: unknown terminal {terminal!r}; known: {', '.join(TERMINALS)} (or a list as a custom prefix)")
        return 1
    label = terminal if isinstance(terminal, str) else str(terminal[0])
    if not shutil.which(command[0]):
        print(f"relay: {command[0]} is not installed. Set [relay] terminal, or ask the user to type /clear.")
        return 1

    close = close_target(env) if config.get("close-old") is True and session else None
    print(f"relay: open a new {label} window in {root} running:\n  {shlex.join(command)}")
    if close:
        print(f"relay: then close this window (hang up {close[1]}, pid {close[0]}) when this turn ends")
    if args.dry_run:
        return 0
    if not confirm("Open the new session?", assume_yes=args.yes or config.get("auto") is True):
        print("relay: cancelled, nothing changed")
        return 1
    error = _launch(command, root, child_env(env, session), new_console=terminal == "console")
    if error:
        print(f"relay: could not open the new session ({error}). Ask the user to type /clear instead.")
        return 1
    if session:
        lock(session, label, close)
    print(
        "relay: the new session is open and continues from the handoff. End your turn now and change "
        "nothing more in this session (its edits are now denied); tell the user in one line."
        + (" This window closes when the turn ends." if close else "")
    )
    return 0
