"""``notify``: a desktop notification when Claude Code waits for you or a long turn ends.

- Notification (permission prompt, idle prompt): forwards Claude Code's message.
- UserPromptSubmit: remembers when the turn started (prints nothing, because
  this event's stdout would reach Claude).
- Stop: notifies when the turn took at least ``min-seconds`` (default 60).

At most one notification per minute across all sessions. Uses ``notify-send``
on Linux and ``osascript`` on macOS; does nothing when neither exists.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import time

from .base import Event, Outcome, State, cache_dir

MIN_INTERVAL = 60.0
MIN_SECONDS = 60


def _allowed(now: float) -> bool:
    stamp = cache_dir() / "notify.last"
    try:
        if 0 <= now - float(stamp.read_text()) < MIN_INTERVAL:
            return False
    except (OSError, ValueError):
        pass
    stamp.write_text(str(now))
    return True


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def send(title: str, body: str) -> bool:
    """Show a desktop notification; False when no notifier is available."""
    if platform.system() == "Darwin" and shutil.which("osascript"):
        command = ["osascript", "-e", f"display notification {_quote(body)} with title {_quote(title)}"]
    elif shutil.which("notify-send"):
        command = ["notify-send", "--app-name=Claude Code", title, body]
    else:
        return False
    try:
        subprocess.run(command, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True


def _duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def handle(event: Event) -> Outcome:
    state = State(event.session_id, "notify")
    now = time.time()
    if event.name == "UserPromptSubmit":
        state.save({"turn_start": now})
        return Outcome()
    title = f"Claude Code · {event.cwd.name or event.cwd}"
    if event.name == "Notification":
        body = str(event.data.get("message") or "Claude Code is waiting for you")
    elif event.name == "Stop":
        start = state.load().get("turn_start")
        threshold = event.config.get("notify", "min-seconds", MIN_SECONDS)
        if not isinstance(start, int | float) or now - start < threshold:
            return Outcome()
        body = f"Done after {_duration(now - start)}"
    else:
        return Outcome()
    if _allowed(now):
        send(title, body)
    return Outcome()
