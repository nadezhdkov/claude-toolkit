"""``ctk hook <name>``: logic behind the claude-toolkit plugin hooks.

Claude Code runs each hook with the event as JSON on stdin. A hook prints
nothing when all is well, skips projects it does not apply to, and never lets
its own failure get in the way: errors are logged and the hook exits 0.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from collections.abc import Callable

from .base import Event, Outcome, cache_dir, load_config

HOOKS = ("format-file", "affected-tests", "guard-destructive", "secrets", "notify", "agent-contract")


def _handler(name: str) -> Callable[[Event], Outcome]:
    if name == "format-file":
        from .format_file import handle
    elif name == "affected-tests":
        from .affected_tests import handle
    elif name == "guard-destructive":
        from .guard import handle
    elif name == "secrets":
        from .secrets import handle
    elif name == "agent-contract":
        from .agent_contract import handle
    else:
        from .notify import handle
    return handle


def dispatch(name: str, raw: str) -> Outcome:
    """Run one hook on the raw stdin payload; never raises."""
    try:
        data = json.loads(raw) if raw.strip() else {}
        event = Event.from_json(data if isinstance(data, dict) else {})
        config = load_config(event.cwd)
        if not config.enabled(name):
            return Outcome()
        event.config = config
        return _handler(name)(event)
    except Exception:  # fail-open: a broken hook must never block Claude Code
        _log_error(name)
        return Outcome()


def run(name: str) -> int:
    outcome = dispatch(name, sys.stdin.read())
    if outcome.stdout:
        print(outcome.stdout)
    if outcome.stderr:
        print(outcome.stderr, file=sys.stderr)
    return outcome.exit_code


def _log_error(name: str) -> None:
    try:
        path = cache_dir() / "errors.log"
        with path.open("a", encoding="utf-8") as log:
            log.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} {name}\n{traceback.format_exc()}")
    except OSError:
        pass
