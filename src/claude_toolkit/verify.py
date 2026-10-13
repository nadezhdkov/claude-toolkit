"""``ctk verify``: what is verified for the code as it is now.

Every ``ctk runq`` run inside a git repository is recorded in a ledger with
its command, exit code, counts, log path, commit and a hash of the exact state
of the working tree (HEAD, uncommitted changes and untracked files). ``ctk
verify`` compares each command's latest record with the current state:

- ✓ fresh and passing, ✗ fresh and failing,
- ~ stale: it ran on a different state of the code, so it proves nothing now,
- ? never: a configured or detected check that has no record.

``ctk verify run`` runs the project's checks (``[verify] commands`` in
``.claude-toolkit.toml``, else detected from the project files) and records
them. A test that did not run never shows as passed, and an old result never
shows as current.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

LEDGER_KEEP = 500
UNTRACKED_HASH_LIMIT = 1024 * 1024


def _git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def repo_root(path: Path) -> Path | None:
    done = _git(path, "rev-parse", "--show-toplevel")
    if done is None or done.returncode != 0:
        return None
    return Path(done.stdout.decode().strip())


@dataclass(frozen=True)
class CodeState:
    commit: str  # short HEAD, or "none" before the first commit
    dirty: bool
    digest: str  # identifies HEAD + uncommitted changes + untracked files


def code_state(root: Path) -> CodeState:
    head = _git(root, "rev-parse", "--short", "HEAD")
    commit = head.stdout.decode().strip() if head and head.returncode == 0 else "none"
    digest = hashlib.sha256(commit.encode())
    changes = _git(root, "diff", "HEAD", "--binary") if commit != "none" else _git(root, "diff", "--cached", "--binary")
    changed = bool(changes and changes.stdout)
    if changes:
        digest.update(changes.stdout)
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    names = [n for n in (untracked.stdout.decode(errors="replace").split("\0") if untracked else []) if n]
    for name in sorted(names):
        path = root / name
        digest.update(name.encode())
        try:
            stat = path.stat()
            if stat.st_size <= UNTRACKED_HASH_LIMIT:
                digest.update(path.read_bytes())
            else:
                digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
        except OSError:
            continue
    return CodeState(commit, changed or bool(names), digest.hexdigest()[:16])


# --- Ledger ---------------------------------------------------------------------------


def ledger_path(root: Path) -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    return Path(base) / "claude-toolkit" / "verify" / f"{key}.jsonl"


@dataclass
class Record:
    command: str
    exit_code: int
    summary: str
    commit: str
    dirty: bool
    state: str
    time: float
    seconds: float
    log: str | None = None


def normalise(command: list[str] | str) -> str:
    return command if isinstance(command, str) else shlex.join(command)


def _summary_line(command: list[str], output: str, exit_code: int) -> str:
    from .runq import ANSI, digest_output

    lines = ANSI.sub("", output).splitlines()
    digest = digest_output(command, lines)
    if digest.summary:
        return re.sub(r"^=+\s*|\s*=+$", "", digest.summary[-1]).strip()[:160]
    if digest.failure_count:
        return f"{digest.failure_count} failure(s)"
    tail = next((line.strip() for line in reversed(lines) if line.strip()), "")
    return tail[:160] if exit_code else (tail[:160] or "ok")


def record(
    command: list[str], cwd: Path, exit_code: int, output: str, seconds: float, log: Path | None = None
) -> Record | None:
    """Append a run to the ledger of the repository around ``cwd``; never raises."""
    try:
        root = repo_root(cwd)
        if root is None:
            return None
        state = code_state(root)
        entry = Record(
            command=normalise(command),
            exit_code=exit_code,
            summary=_summary_line(command, output, exit_code),
            commit=state.commit,
            dirty=state.dirty,
            state=state.digest,
            time=round(time.time(), 1),
            seconds=round(seconds, 1),
            log=str(log) if log else None,
        )
        path = ledger_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as ledger:
            ledger.write(json.dumps(asdict(entry)) + "\n")
        _trim(path)
        return entry
    except Exception:  # recording must never break the command that ran
        return None


def _trim(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > LEDGER_KEEP * 2:
        path.write_text("\n".join(lines[-LEDGER_KEEP:]) + "\n", encoding="utf-8")


def read_ledger(root: Path) -> list[Record]:
    try:
        lines = ledger_path(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            records.append(Record(**json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return records


# --- Checks -----------------------------------------------------------------------------------


def configured_checks(root: Path) -> list[str] | None:
    path = root / ".claude-toolkit.toml"
    if not path.exists():
        return None
    try:
        table = tomllib.loads(path.read_text()).get("verify", {})
    except (OSError, tomllib.TOMLDecodeError) as error:
        print(f"verify: ignoring {path.name}: {error}", file=sys.stderr)
        return None
    commands = table.get("commands") if isinstance(table, dict) else None
    return [str(c) for c in commands] if isinstance(commands, list) and commands else None


def _python_runner(root: Path) -> list[str] | None:
    if (root / ".venv" / "bin" / "python").exists():
        return [".venv/bin/python", "-m"]
    if (root / "uv.lock").exists() and shutil.which("uv"):
        return ["uv", "run", "--frozen", "python", "-m"]
    return None


def detected_checks(root: Path) -> list[str]:
    checks: list[str] = []
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(errors="replace")
        runner = _python_runner(root)
        if runner and ("pytest" in text or (root / "tests").is_dir()):
            checks.append(shlex.join([*runner, "pytest", "-q"]))
        if runner and ("[tool.ruff" in text or (root / "ruff.toml").exists()):
            checks.append(shlex.join([*runner, "ruff", "check", "."]))
    package = root / "package.json"
    if package.exists():
        try:
            scripts = json.loads(package.read_text()).get("scripts") or {}
        except json.JSONDecodeError:
            scripts = {}
        manager = "pnpm" if (root / "pnpm-lock.yaml").exists() else "yarn" if (root / "yarn.lock").exists() else "npm"
        for script in ("test", "lint", "typecheck"):
            if script in scripts and "no test specified" not in str(scripts[script]):
                checks.append(f"{manager} run {script}")
    if (root / "go.mod").exists():
        checks += ["go vet ./...", "go test ./..."]
    if (root / "Cargo.toml").exists():
        checks.append("cargo test")
    return checks


def project_checks(root: Path) -> tuple[list[str], str]:
    configured = configured_checks(root)
    checks, source = (configured, "configured") if configured else (detected_checks(root), "detected")
    return [normalise(shlex.split(command)) for command in checks], source


# --- Status -------------------------------------------------------------------------------------


@dataclass
class Status:
    command: str
    verdict: str  # pass, fail, stale, never
    record: Record | None


def status(root: Path) -> tuple[CodeState, list[Status]]:
    state = code_state(root)
    latest: dict[str, Record] = {}
    for entry in read_ledger(root):
        latest[entry.command] = entry
    checks, _ = project_checks(root)
    result = []
    for command in dict.fromkeys([*checks, *latest]):
        entry = latest.get(command)
        if entry is None:
            verdict = "never"
        elif entry.state != state.digest:
            verdict = "stale"
        else:
            verdict = "pass" if entry.exit_code == 0 else "fail"
        result.append(Status(command, verdict, entry))
    return state, result


def _ago(seconds: float) -> str:
    seconds = max(0, seconds)
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size:.0f}{unit} ago"
    return "just now"


SYMBOLS = {"pass": "✓ pass ", "fail": "✗ fail ", "stale": "~ stale", "never": "? never"}


def render(root: Path, state: CodeState, statuses: list[Status]) -> str:
    from .style import Style, shorten_home

    st = Style.detect()
    where = f"{state.commit}" + (" + uncommitted changes" if state.dirty else "")
    lines = [f"verify: {shorten_home(root)} · {where}"]
    if not statuses:
        lines.append("  no checks recorded or detected (configure [verify] commands in .claude-toolkit.toml)")
    width = max((len(s.command) for s in statuses), default=0)
    width = min(width, 48)
    paint = {"pass": st.ok, "fail": st.err, "stale": st.warn, "never": st.muted}
    for item in statuses:
        entry = item.record
        if entry is None:
            detail = "no record for this code"
        elif item.verdict == "stale":
            changed = "uncommitted changes" if entry.commit == state.commit else f"commit {entry.commit}"
            when = _ago(time.time() - entry.time)
            detail = f"exit {entry.exit_code} · {entry.summary} · ran on {changed}, code changed since · {when}"
        else:
            detail = f"exit {entry.exit_code} · {entry.summary} · {_ago(time.time() - entry.time)}"
        command = item.command if len(item.command) <= width else item.command[: width - 1] + "…"
        lines.append(f"  {paint[item.verdict](SYMBOLS[item.verdict])}  {command.ljust(width)}  {detail}")
        if item.verdict == "fail" and entry and entry.log:
            lines.append(f"  {'':<7}  {'':<{width}}  log: {shorten_home(entry.log)}")
    return "\n".join(lines)


def run_checks(root: Path) -> list[Record]:
    from .runq import execute

    checks, _ = project_checks(root)
    records = []
    for command in checks:
        argv = shlex.split(command)
        try:
            done = execute(argv, cwd=root)
        except FileNotFoundError:
            print(f"verify: command not found: {argv[0]}", file=sys.stderr)
            continue
        entry = record(argv, root, done.exit_code, done.output, done.elapsed, done.log_path)
        if entry:
            records.append(entry)
    return records


def run(args) -> int:
    root = repo_root(Path(args.path).expanduser().resolve())
    if root is None:
        print("verify: not inside a git repository", file=sys.stderr)
        return 1
    if args.action == "run":
        from .style import Spinner

        checks, source = project_checks(root)
        if not checks:
            print("verify: no checks configured or detected; add [verify] commands to .claude-toolkit.toml")
            return 1
        with Spinner(f"running {len(checks)} {source} check(s)"):
            run_checks(root)
    state, statuses = status(root)
    if args.json:
        print(json.dumps({"state": asdict(state), "checks": [asdict(s) for s in statuses]}, indent=2))
    else:
        print(render(root, state, statuses))
    return 0 if statuses and all(s.verdict == "pass" for s in statuses) else 1
