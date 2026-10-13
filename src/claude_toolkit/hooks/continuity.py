"""``continuity`` (SessionStart after a compaction): bring back the verified state of the work.

A compaction replaces the conversation with a summary. This hook adds facts
that do not depend on that summary: the branch, commit and uncommitted
changes, what ``ctk verify`` knows for the code as it is now (stale results
marked as such), and the branch's handoff file with its date. Silent outside
a git repository or when there is nothing to report.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .base import Event, Outcome

HANDOFF_LINES = 60


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


def summary(root: Path) -> str | None:
    from ..verify import SYMBOLS, status

    branch = _git(root, "branch", "--show-current") or "(detached HEAD)"
    changed = [line for line in _git(root, "status", "--porcelain").splitlines() if line.strip()]
    state, checks = status(root)
    lines = [
        "ctk continuity, after a compaction: verified state of this work (facts, not memory).",
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
    if not checks and not handoff and not changed:
        return None
    lines.append("Re-run stale checks before relying on them; never report a check as passing from memory.")
    return "\n".join(lines)


def handle(event: Event) -> Outcome:
    if event.name != "SessionStart" or event.data.get("source") != "compact":
        return Outcome()
    from ..verify import repo_root

    root = repo_root(event.cwd)
    if root is None:
        return Outcome()
    text = summary(root)
    return Outcome.context("SessionStart", text) if text else Outcome()
