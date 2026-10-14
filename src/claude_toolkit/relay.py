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
same worktree.
"""

from __future__ import annotations

import os
import shlex
import shutil
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

# name -> (binary, prefix before the command, given the working directory)
TERMINALS: dict[str, tuple[str, Callable[[str], list[str]]]] = {
    "tmux": ("tmux", lambda cwd: ["tmux", "new-window", "-c", cwd, "-n", "relay", "--"]),
    "konsole": ("konsole", lambda cwd: ["konsole", "--workdir", cwd, "-e"]),
    "kitty": ("kitty", lambda cwd: ["kitty", "--directory", cwd, "--"]),
    "alacritty": ("alacritty", lambda cwd: ["alacritty", "--working-directory", cwd, "-e"]),
    "wezterm": ("wezterm", lambda cwd: ["wezterm", "start", "--cwd", cwd, "--"]),
    "ghostty": ("ghostty", lambda cwd: ["ghostty", f"--working-directory={cwd}", "-e"]),
    "gnome-terminal": ("gnome-terminal", lambda cwd: ["gnome-terminal", f"--working-directory={cwd}", "--"]),
    "foot": ("foot", lambda cwd: ["foot", "-D", cwd]),
    "xterm": ("xterm", lambda cwd: ["xterm", "-e"]),
}
# The terminal Claude Code itself runs in, recognised by its environment.
MARKERS = (
    ("tmux", "TMUX"),
    ("konsole", "KONSOLE_VERSION"),
    ("kitty", "KITTY_WINDOW_ID"),
    ("alacritty", "ALACRITTY_WINDOW_ID"),
    ("alacritty", "ALACRITTY_SOCKET"),
    ("wezterm", "WEZTERM_PANE"),
    ("ghostty", "GHOSTTY_RESOURCES_DIR"),
    ("gnome-terminal", "GNOME_TERMINAL_SCREEN"),
)
FALLBACK_ORDER = ("konsole", "alacritty", "kitty", "gnome-terminal", "wezterm", "ghostty", "foot", "xterm")


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


def detect_terminal(env: Mapping[str, str], which: Callable[[str], str | None] = shutil.which) -> str | None:
    """The terminal Claude Code runs in, else the first installed one (graphical ones need a display)."""
    for name, variable in MARKERS:
        if env.get(variable) and which(TERMINALS[name][0]):
            return name
    if env.get("TERM") == "foot" and which("foot"):
        return "foot"
    if not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        return None
    return next((name for name in FALLBACK_ORDER if which(TERMINALS[name][0])), None)


def claude_command(branch: str, env: Mapping[str, str], extra: list[str]) -> list[str]:
    command = ["claude", "--name", f"relay {branch}"]
    if env.get("CLAUDE_EFFORT"):
        command += ["--effort", env["CLAUDE_EFFORT"]]
    return [*command, *extra, FIRST_PROMPT]


def terminal_command(terminal: str | list[str], cwd: Path, command: list[str]) -> list[str] | None:
    """A known terminal's name, or a custom prefix (``{cwd}`` is replaced), followed by ``command``."""
    if isinstance(terminal, list):
        return [str(part).replace("{cwd}", str(cwd)) for part in terminal] + command
    known = TERMINALS.get(terminal)
    return known[1](str(cwd)) + command if known else None


def child_env(env: Mapping[str, str], from_session: str | None) -> dict[str, str]:
    child = {key: value for key, value in env.items() if key not in SESSION_ENV}
    child["CTK_RELAY"] = "1"
    if from_session:
        child["CTK_RELAY_FROM"] = from_session
    return child


# --- Lock of the old session ----------------------------------------------------------


def lock(session_id: str, terminal: str) -> None:
    state = State(session_id, "relay")
    data = state.load()
    data.update({"relayed_at": time.time(), "terminal": terminal})
    state.save(data)


def locked(session_id: str) -> bool:
    return bool(State(session_id, "relay").load().get("relayed_at"))


def release(session_id: str) -> None:
    state = State(session_id, "relay")
    data = state.load()
    data.pop("relayed_at", None)
    state.save(data)


# --- Command -------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _launch(command: list[str], cwd: Path, env: dict[str, str]) -> str | None:
    """Start the terminal detached; an error message if it could not start or failed at once."""
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
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
    command = terminal_command(terminal, root, claude_command(branch, env, extra))
    if command is None:
        print(f"relay: unknown terminal {terminal!r}; known: {', '.join(TERMINALS)} (or a list as a custom prefix)")
        return 1
    label = terminal if isinstance(terminal, str) else str(terminal[0])
    if not shutil.which(command[0]):
        print(f"relay: {command[0]} is not installed. Set [relay] terminal, or ask the user to type /clear.")
        return 1

    print(f"relay: open a new {label} window in {root} running:\n  {shlex.join(command)}")
    if args.dry_run:
        return 0
    if not confirm("Open the new session?", assume_yes=args.yes or config.get("auto") is True):
        print("relay: cancelled, nothing changed")
        return 1
    error = _launch(command, root, child_env(env, session))
    if error:
        print(f"relay: could not open the new session ({error}). Ask the user to type /clear instead.")
        return 1
    if session:
        lock(session, label)
    print(
        "relay: the new session is open and continues from the handoff. End your turn now and change "
        "nothing more in this session (its edits are now denied); tell the user in one line."
    )
    return 0
