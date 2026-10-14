"""``relay`` (Stop, PreToolUse on edits): move a session that grew too large to a fresh one.

At the end of a turn (a safe point: no edit is half done) it reads the
session's current window from the transcript. Once that passes the threshold
(``[hooks.relay] threshold``; ``ctk sessions`` shows the relay point for your
own sessions), it asks Claude, once per session, to bring the handoff file up
to date and run ``ctk relay``. After a relay, the old session's edits are
denied, so two sessions never edit the same worktree; with ``[relay] close-old``
the end of its next turn closes its window.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Event, Outcome, State

DEFAULT_THRESHOLD = 300_000  # the relay point of the maintainer's sessions, 2026-10 (`ctk sessions`)
TAIL_BYTES = 512 * 1024
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def current_window(transcript: Path) -> int | None:
    """Tokens the last main-thread model call read, from the end of the transcript."""
    try:
        with transcript.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        if '"usage"' not in line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("isSidechain"):
            continue
        message = record.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if isinstance(usage, dict):
            keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
            return sum(int(usage.get(key) or 0) for key in keys)
    return None


def _close(state: State, data: dict) -> None:
    """The turn after a relay ended: close the old window that ``ctk relay`` recorded, once."""
    from ..relay import close_later

    target = data.pop("close")
    state.save(data)
    if isinstance(target, list) and len(target) == 2 and isinstance(target[0], int):
        close_later(int(target[0]), str(target[1]))


def _ask(event: Event) -> Outcome:
    state = State(event.session_id, "relay")
    data = state.load()
    if data.get("relayed_at") and data.get("close"):
        _close(state, data)
        return Outcome()
    if event.data.get("stop_hook_active"):
        return Outcome()
    if data.get("asked") or data.get("relayed_at"):
        return Outcome()
    transcript = event.data.get("transcript_path")
    window = current_window(Path(str(transcript))) if transcript else None
    threshold = event.config.get("relay", "threshold", DEFAULT_THRESHOLD)
    if window is None or window < threshold:
        return Outcome()
    data["asked"] = window
    state.save(data)
    reason = (
        f"ctk relay: this session's context window is {window:,} tokens (relay point {threshold:,}), and every "
        "call re-reads all of it. This is a safe point to hand the work over to a fresh session:\n"
        "1. Bring the branch's handoff file up to date (/ctk:handoff write): goal, decisions, next step.\n"
        "2. Run `ctk relay`. If it opens the new session, end your turn and change nothing more here. "
        "If it exits 3, show the user its plan and ask them to approve it (they can run `! ctk relay --yes`). "
        "If it finds no terminal, ask the user to type /clear.\n"
        "If the user asked for something that is not finished, finish it first and say so in one line. "
        "This is asked once per session."
    )
    return Outcome.json({"decision": "block", "reason": reason})


def _deny_edit(event: Event) -> Outcome:
    if str(event.data.get("tool_name", "")) not in EDIT_TOOLS:
        return Outcome()
    if not State(event.session_id, "relay").load().get("relayed_at"):
        return Outcome()
    reason = (
        "ctk relay: this session handed the work over to a new session, which may be editing this worktree now. "
        "Do not change files here; tell the user. To keep working in this session instead, "
        f"the user can run `! ctk relay --release --session {event.session_id}`."
    )
    return Outcome.json(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def handle(event: Event) -> Outcome:
    if event.name == "Stop":
        return _ask(event)
    if event.name == "PreToolUse":
        return _deny_edit(event)
    return Outcome()
