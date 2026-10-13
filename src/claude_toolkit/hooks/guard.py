"""``guard-destructive`` (PreToolUse on Bash): catch commands that destroy work.

Rules: ``rm`` with both recursive and force flags on a path outside the
project (temporary directories excepted), a force-push to a protected branch,
and ``git reset --hard`` while tracked files have uncommitted changes.

The mode starts as ``warn``: the user sees a warning, the command runs and the
match is logged so false positives can be reviewed. With ``mode = "block"``
the command is denied and Claude is told why.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

from .base import Event, Outcome, cache_dir, is_within, project_root
from .shell import GitCommand, SimpleCommand, as_git, expand, split

PROTECTED = ["main", "master"]
GLOB = set("*?[")
PUSH_VALUE_OPTIONS = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}


def log_path() -> Path:
    return cache_dir() / "guard.log"


def _git(cwd: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


# --- rm -rf -------------------------------------------------------------------


def _rm_flags(args: list[str]) -> tuple[bool, bool, list[str]]:
    recursive = force = False
    targets: list[str] = []
    options_done = False
    for arg in args:
        if options_done or not arg.startswith("-") or arg == "-":
            targets.append(arg)
        elif arg == "--":
            options_done = True
        elif arg.startswith("--"):
            recursive |= arg == "--recursive"
            force |= arg == "--force"
        else:
            recursive |= "r" in arg or "R" in arg
            force |= "f" in arg
    return recursive, force, targets


def temp_dirs(event: Event) -> list[Path]:
    temps = {Path(tempfile.gettempdir()), Path("/tmp"), Path("/var/tmp")}
    scratch = event.data.get("scratchpad_dir")
    if scratch:
        temps.add(Path(str(scratch)))
    return sorted(temps)


def _safe_roots(root: Path, event: Event) -> tuple[Path | None, list[Path]]:
    project = None if root in (Path.home(), Path("/")) else root
    return project, temp_dirs(event)


def _strictly_inside(path: Path, root: Path) -> bool:
    return path != root and is_within(path, root)


def _rm_target_safe(word: str, cwd: Path, project: Path | None, temps: list[Path]) -> bool:
    path = expand(word, cwd)
    if path is None:
        return False
    if project is not None and is_within(project, path):
        return False  # the project itself or one of its parents
    parts = path.parts
    glob_at = next((i for i, part in enumerate(parts) if GLOB & set(part)), None)
    if glob_at is not None:
        base = Path(*parts[:glob_at])
        # `rm -rf *` in the project deletes its children; allowed like any path inside it.
        return (project is not None and is_within(base, project)) or any(_strictly_inside(base, temp) for temp in temps)
    return any(_strictly_inside(path, root) for root in [project, *temps] if root is not None)


def check_rm(command: SimpleCommand, project: Path | None, temps: list[Path]) -> str | None:
    if command.name != "rm":
        return None
    recursive, force, targets = _rm_flags(command.argv[1:])
    if not (recursive and force):
        return None
    outside = [word for word in targets if not _rm_target_safe(word, command.cwd, project, temps)]
    if not outside:
        return None
    where = "outside the project" if project else "with no project around it"
    return f"`rm -rf` {where}: {', '.join(outside[:3])}"


# --- git push --force -------------------------------------------------------------


def check_push(git: GitCommand, protected: list[str]) -> str | None:
    if git.subcommand != "push":
        return None
    forced = every = False
    positional: list[str] = []
    args = iter(git.args)
    for arg in args:
        if arg in ("-f", "--force") or arg.startswith("--force-with-lease"):
            forced = True
        elif arg in ("--all", "--mirror", "--branches"):
            every = True
        elif arg in PUSH_VALUE_OPTIONS:
            next(args, None)
        elif arg.startswith("--"):
            continue
        elif arg.startswith("-"):
            forced |= "f" in arg[1:]
        else:
            positional.append(arg)
    refspecs = positional[1:]
    targets: list[str] = []
    for spec in refspecs:
        plus = spec.startswith("+")
        destination = spec.lstrip("+").split(":", 1)[-1].removeprefix("refs/heads/")
        if destination in ("", "HEAD"):
            destination = _git(git.cwd, "symbolic-ref", "--short", "-q", "HEAD") or ""
        if (forced or plus) and destination in protected:
            targets.append(destination)
    if forced and not refspecs:
        if every:
            targets.extend(protected)
        else:
            branch = _git(git.cwd, "symbolic-ref", "--short", "-q", "HEAD")
            if branch in protected:
                targets.append(branch)
    if not targets:
        return None
    return f"force-push to {', '.join(sorted(set(targets)))}"


# --- git reset --hard -------------------------------------------------------------


def check_reset(git: GitCommand) -> str | None:
    if git.subcommand != "reset" or "--hard" not in git.args:
        return None
    changes = _git(git.cwd, "status", "--porcelain", "--untracked-files=no")
    if not changes:
        return None
    count = len(changes.splitlines())
    return f"`git reset --hard` would discard uncommitted changes in {count} tracked file(s)"


def check(command: str, event: Event) -> list[str]:
    root = project_root(event.cwd)
    project, temps = _safe_roots(root, event)
    protected = event.config.get("guard-destructive", "protected-branches", PROTECTED)
    reasons: list[str] = []
    for simple in split(command, event.cwd):
        found = [check_rm(simple, project, temps)]
        git = as_git(simple)
        if git:
            found += [check_push(git, [str(name) for name in protected]), check_reset(git)]
        reasons.extend(reason for reason in found if reason and reason not in reasons)
    return reasons


def _record(mode: str, reasons: list[str], command: str, cwd: Path) -> None:
    entry = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": mode,
        "reasons": reasons,
        "cwd": str(cwd),
        "command": command[:500],
    }
    try:
        with log_path().open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def handle(event: Event) -> Outcome:
    command = event.tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return Outcome()
    reasons = check(command, event)
    if not reasons:
        return Outcome()
    mode = event.config.get("guard-destructive", "mode", "warn")
    mode = mode if mode in ("warn", "block") else "warn"
    _record(mode, reasons, command, event.cwd)
    summary = "; ".join(reasons)
    if mode == "block":
        reason = (
            f"guard-destructive blocked this command: {summary}. "
            "If it is really intended, ask the user to run it themselves."
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
    return Outcome.message(f"⚠ guard-destructive (warn-only): {summary}. Logged in {log_path()}.")


def show_log(limit: int = 50) -> str:
    """Recent matches, newest last, for reviewing false positives."""
    try:
        lines = log_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return "guard-destructive: no matches recorded"
    out = []
    for line in lines[-limit:]:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(f"{entry['time']}  {entry['mode']:<5}  {'; '.join(entry['reasons'])}  ·  {entry['command']}")
    return "\n".join(out) if out else "guard-destructive: no matches recorded"
