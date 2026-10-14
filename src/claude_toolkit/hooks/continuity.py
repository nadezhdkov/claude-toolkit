"""``continuity`` (SessionStart): bring back the verified state of the work.

A compaction replaces the conversation with a summary, ``/clear`` and a relay
(``ctk relay``) start from nothing, and a resumed session may be days old.
This hook adds facts that do not depend on any of that: the branch, commit and
uncommitted changes, what ``ctk verify`` knows for the code as it is now
(stale results marked as such), and the branch's handoff file with its date.
It runs after a compaction, ``/clear`` and a resume, and at the start of a
session that ``ctk relay`` opened (``CTK_RELAY`` in the environment). Silent
outside a git repository or when there is nothing to report.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .base import Event, Outcome

HANDOFF_LINES = 60
HEADERS = {
    "compact": "after a compaction",
    "clear": "after /clear",
    "resume": "on resume",
    "relay": "handed over by ctk relay from a previous session",
}


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def handoff_file(root: Path, branch: str) -> Path | None:
    """The handoff skill's default location: .claude/handoff/<branch with / as ->.md."""
    name = branch.replace("/", "-").replace("\\", "-")
    path = root / ".claude" / "handoff" / f"{name}.md"
    return path if path.is_file() else None


def _age(seconds: float) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size:.0f}{unit} ago"
    return "just now"


def summary(root: Path, source: str = "compact") -> str | None:
    from ..verify import SYMBOLS, status

    branch = _git(root, "branch", "--show-current") or "(detached HEAD)"
    changed = [line for line in _git(root, "status", "--porcelain").splitlines() if line.strip()]
    state, checks = status(root)
    lines = [
        f"ctk continuity, {HEADERS.get(source, source)}: verified state of this work (facts, not memory).",
        f"branch {branch} · HEAD {state.commit}"
        + (f" + {len(changed)} uncommitted file(s)" if changed else " · working tree clean"),
    ]
    if checks:
        lines.append("checks (ctk verify, for the code as it is now):")
        for check in checks[:8]:
            record = check.record
            detail = f" · {record.summary}" if record and check.verdict in ("pass", "fail") else ""
            lines.append(f"  {SYMBOLS[check.verdict].strip()}  {check.command}{detail}")
    handoff = handoff_file(root, branch)
    if handoff:
        text = handoff.read_text(errors="replace").splitlines()
        age = _age(time.time() - handoff.stat().st_mtime)
        lines.append(f"handoff {handoff.relative_to(root)} (written {age}; check it against the code):")
        lines += [f"  {line}" for line in text[:HANDOFF_LINES]]
        if len(text) > HANDOFF_LINES:
            lines.append(f"  … {len(text) - HANDOFF_LINES} more lines in the file")
    if not checks and not handoff and not changed and source != "relay":
        return None
    lines.append("Re-run stale checks before relying on them; never report a check as passing from memory.")
    if source == "relay":
        lines.append(
            "Resume from the handoff: check it against the code, tell the user in three lines the goal, "
            "where it stands and the next step, then continue with that step."
        )
    return "\n".join(lines)


def handle(event: Event) -> Outcome:
    if event.name != "SessionStart":
        return Outcome()
    source = str(event.data.get("source") or "")
    if source == "startup" and os.environ.get("CTK_RELAY"):
        source = "relay"
    if source not in HEADERS:
        return Outcome()
    from ..verify import repo_root

    root = repo_root(event.cwd)
    if root is None:
        return Outcome()
    text = summary(root, source)
    return Outcome.context("SessionStart", text) if text else Outcome()
