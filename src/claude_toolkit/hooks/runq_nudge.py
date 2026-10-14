"""``runq-nudge`` (after Bash): point long command output at ``ctk runq`` before it piles up.

A tool result stays in the window and is read again by every later model
call, so a few thousand lines of test output cost far more than their size.
When a Bash command that did not go through ``ctk`` prints more than
``[hooks.runq-nudge] min-chars``, Claude is told once per command name (at
most ``max-per-session`` times) to use ``ctk runq`` or filter the output.
"""

from __future__ import annotations

import re

from .base import Event, Outcome, State

DEFAULT_MIN_CHARS = 8_000  # ~2,000 tokens
DEFAULT_MAX = 3
CTK = re.compile(r"(?:^|[\s;&|(])ctk\s")


def output_chars(response: object) -> int:
    if isinstance(response, str):
        return len(response)
    if isinstance(response, dict):
        return sum(len(value) for key in ("stdout", "stderr", "output") if isinstance(value := response.get(key), str))
    if isinstance(response, list):
        return sum(len(item.get("text", "")) for item in response if isinstance(item, dict))
    return 0


WRAPPERS = {"sudo", "time", "env", "nice", "uv", "uvx", "npx", "pnpm", "bunx", "run", "exec"}


def command_name(command: str) -> str:
    """The program a command line runs: its last ``&&``/``;`` part, past ``cd``, variables and wrappers."""
    parts = [part.strip() for part in re.split(r"&&|;|\|\|", command) if part.strip()]
    parts = [part for part in parts if not part.startswith("cd ")] or parts
    for word in parts[-1].split() if parts else []:
        if ("=" in word and not word.startswith("=")) or word in WRAPPERS:
            continue
        return word.rsplit("/", 1)[-1]
    return ""


def handle(event: Event) -> Outcome:
    if event.name != "PostToolUse" or event.data.get("tool_name") != "Bash":
        return Outcome()
    command = str(event.tool_input.get("command", ""))
    if not command or CTK.search(f" {command}"):
        return Outcome()
    size = output_chars(event.data.get("tool_response"))
    if size < event.config.get("runq-nudge", "min-chars", DEFAULT_MIN_CHARS):
        return Outcome()
    state = State(event.session_id, "runq-nudge")
    data = state.load()
    nudged = data.get("nudged", [])
    name = command_name(command)
    if name in nudged or len(nudged) >= event.config.get("runq-nudge", "max-per-session", DEFAULT_MAX):
        return Outcome()
    state.save({"nudged": [*nudged, name]})
    text = (
        f"ctk runq-nudge: that command printed ~{size // 4:,} tokens, which every later call in this session "
        "re-reads. For tests, builds and linters run `ctk runq -- <command>` (failures, summary and log path "
        "only); for other long output, filter it (grep, head, tail) or write it to a file and read what you need."
    )
    return Outcome.context("PostToolUse", text)
