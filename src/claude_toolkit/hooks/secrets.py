"""``secrets`` (PreToolUse on Bash): scan with gitleaks before ``git commit``.

Staged changes are scanned (plus unstaged ones for ``commit -a``); findings
deny the commit and list file, line and rule only, never the secret itself.
Without gitleaks the hook says so once per session and lets commits through.
``ctk hook secrets --git`` does the same scan as a plain git pre-commit hook.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ..common import parse_version, run_text
from .base import Event, Outcome, State, git_root
from .shell import as_git, split

TIMEOUT = 60
MAX_LISTED = 10


def _commit_targets(command: str, cwd: Path) -> list[tuple[Path, bool]]:
    """(repository, includes unstaged changes) for each ``git commit`` in the command."""
    found: list[tuple[Path, bool]] = []
    for simple in split(command, cwd):
        git = as_git(simple)
        if not git or git.subcommand != "commit":
            continue
        every = any(arg in ("-a", "--all") or (arg[:2] != "--" and arg[:1] == "-" and "a" in arg) for arg in git.args)
        repo = git_root(git.cwd)
        if repo:
            found.append((repo, every))
    return found


def _gitleaks_commands(tool: str, repo: Path, unstaged: bool) -> list[list[str]]:
    common = ["--redact", "--no-banner", "--exit-code", "1", "--report-format", "json"]
    version = parse_version(run_text([tool, "version"]))
    if version and version >= (8, 19, 0):
        commands = [[tool, "git", "--pre-commit", "--staged", *common, str(repo)]]
        if unstaged:
            commands.append([tool, "git", "--pre-commit", *common, str(repo)])
    else:
        commands = [[tool, "protect", "--staged", *common, "--source", str(repo)]]
        if unstaged:
            commands.append([tool, "protect", *common, "--source", str(repo)])
    return commands


def scan(repo: Path, *, unstaged: bool = False) -> list[str] | None:
    """Findings as ``file:line rule`` lines; None when gitleaks is missing or fails."""
    tool = shutil.which("gitleaks")
    if not tool:
        return None
    findings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ctk-gitleaks-") as tmp:
        for index, base in enumerate(_gitleaks_commands(tool, repo, unstaged)):
            report = Path(tmp) / f"report-{index}.json"
            command = [*base, "--report-path", str(report)]
            try:
                done = subprocess.run(
                    command,
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT,
                    check=False,
                    encoding="utf-8",
                    errors="replace",
                )
            except (OSError, subprocess.TimeoutExpired):
                return None
            if done.returncode not in (0, 1):
                return None
            try:
                items = json.loads(report.read_text(encoding="utf-8")) if report.exists() else []
            except (OSError, json.JSONDecodeError):
                items = []
            for item in items if isinstance(items, list) else []:
                line = f"{item.get('File', '?')}:{item.get('StartLine', '?')} {item.get('RuleID', 'secret')}"
                if line not in findings:
                    findings.append(line)
    return findings


def _listing(findings: list[str]) -> str:
    shown = findings[:MAX_LISTED]
    more = len(findings) - len(shown)
    return "\n".join([*(f"  {line}" for line in shown), *([f"  … and {more} more"] if more > 0 else [])])


def handle(event: Event) -> Outcome:
    command = event.tool_input.get("command")
    if not isinstance(command, str) or "commit" not in command:
        return Outcome()
    targets = _commit_targets(command, event.cwd)
    if not targets:
        return Outcome()
    if not shutil.which("gitleaks"):
        state = State(event.session_id, "secrets")
        if state.load().get("warned"):
            return Outcome()
        state.save({"warned": True})
        return Outcome.message(
            "secrets: gitleaks is not installed, so commits are not scanned for secrets (see `ctk doctor --toolkit`)."
        )
    findings: list[str] = []
    for repo, unstaged in targets:
        findings += scan(repo, unstaged=unstaged) or []
    if not findings:
        return Outcome()
    reason = (
        f"secrets: gitleaks found {len(findings)} possible secret(s) in the changes to be committed:\n"
        f"{_listing(findings)}\n"
        "Remove them (or add a reviewed entry to .gitleaksignore) before committing."
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


def git_pre_commit() -> int:
    """Entry point for ``.git/hooks/pre-commit``: exit 1 when secrets are staged."""
    repo = git_root(Path.cwd())
    if repo is None:
        return 0
    findings = scan(repo)
    if findings is None:
        if not shutil.which("gitleaks"):
            print("secrets: gitleaks is not installed; commit not scanned", file=sys.stderr)
        return 0
    if findings:
        print(f"secrets: gitleaks found {len(findings)} possible secret(s):\n{_listing(findings)}", file=sys.stderr)
        return 1
    return 0
