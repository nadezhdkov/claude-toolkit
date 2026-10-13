"""``affected-tests``: run the tests touched by this turn's edits when Claude stops.

PostToolUse (Edit/Write) records each edited file for the session. On Stop the
files are mapped to tests and run through ``ctk runq``'s machinery:

- Python: ``test_<name>.py``/``<name>_test.py`` for each edited module, with
  pytest from the project's ``.venv`` or ``uv run``;
- JavaScript/TypeScript: ``vitest related`` or ``jest --findRelatedTests``;
- Go: ``go test`` for the edited packages.

Silent when the tests pass or nothing applies. On failure Claude is asked to
continue with the failure digest, once; if the tests still fail after that, the
user gets a short warning instead, so the hook can never loop.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import runq
from ..style import Style
from .base import Event, Outcome, State, is_within, project_root
from .format_file import SKIP_DIRS

TIMEOUT = 240
MAX_REASON = 6000
MAX_WALK = 20000
JS_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".vue", ".svelte"}
PY_TEST = re.compile(r"^(test_.+|.+_test)\.py$")
# Not setup.py: packages often contain a module of that name.
PY_MARKERS = ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")


@dataclass
class Plan:
    label: str
    command: list[str]
    cwd: Path
    ok_codes: set[int] = field(default_factory=lambda: {0})


def _nearest(file: Path, root: Path, markers: tuple[str, ...]) -> Path | None:
    for directory in file.parents:
        if not is_within(directory, root):
            break
        if any((directory / marker).exists() for marker in markers):
            return directory
    return None


def _walk(base: Path):
    seen = 0
    for directory, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            seen += 1
            if seen > MAX_WALK:
                return
            yield Path(directory) / name


# --- Python -------------------------------------------------------------------


def _pytest_command(project: Path) -> list[str] | None:
    python = project / ".venv" / "bin" / "python"
    if python.exists() and any((project / ".venv" / "lib").glob("python*/site-packages/pytest")):
        return [str(python), "-m", "pytest"]
    pyproject = project / "pyproject.toml"
    uses_uv = (project / "uv.lock").exists() and shutil.which("uv") and pyproject.exists()
    if uses_uv and "pytest" in pyproject.read_text(errors="replace"):
        return ["uv", "run", "--frozen", "pytest"]
    return None


def python_tests(files: list[Path], project: Path) -> list[Path]:
    """Test files for edited Python files: the tests themselves, then ``test_<module>.py`` matches."""
    tests: list[Path] = []
    wanted: set[str] = set()
    for file in files:
        if PY_TEST.match(file.name):
            tests.append(file)
        elif file.name == "conftest.py":
            tests.append(file.parent)
        else:
            stem = file.parent.name if file.stem == "__init__" else file.stem
            wanted.update({f"test_{stem}.py", f"{stem}_test.py"})
    if wanted:
        tests.extend(path for path in _walk(project) if path.name in wanted)
    unique: list[Path] = []
    for test in tests:
        if test.exists() and test not in unique:
            unique.append(test)
    return unique


def _python_plans(files: list[Path], root: Path) -> list[Plan]:
    by_project: dict[Path, list[Path]] = {}
    for file in files:
        if file.suffix == ".py":
            by_project.setdefault(_nearest(file, root, PY_MARKERS) or root, []).append(file)
    plans = []
    for project, edited in by_project.items():
        command = _pytest_command(project)
        tests = python_tests(edited, project) if command else []
        if command and tests:
            relative = [str(test.relative_to(project)) for test in tests]
            plans.append(Plan("pytest", [*command, "-q", *relative], project, {0, 5}))
    return plans


# --- JavaScript / TypeScript ----------------------------------------------------


def _js_plans(files: list[Path], root: Path) -> list[Plan]:
    by_project: dict[Path, list[Path]] = {}
    for file in files:
        if file.suffix in JS_SUFFIXES:
            project = _nearest(file, root, ("package.json",))
            if project:
                by_project.setdefault(project, []).append(file)
    plans = []
    for project, edited in by_project.items():
        relative = [str(file.relative_to(project)) for file in edited]
        bins = [directory / "node_modules" / ".bin" for directory in (project, *project.parents)]
        vitest = next((b / "vitest" for b in bins if (b / "vitest").exists()), None)
        jest = next((b / "jest" for b in bins if (b / "jest").exists()), None)
        if vitest:
            plans.append(Plan("vitest", [str(vitest), "related", "--run", "--passWithNoTests", *relative], project))
        elif jest:
            command = [str(jest), "--passWithNoTests", "--findRelatedTests", *relative]
            plans.append(Plan("jest", command, project))
    return plans


# --- Go -------------------------------------------------------------------------


def _go_plans(files: list[Path], root: Path) -> list[Plan]:
    if not shutil.which("go"):
        return []
    by_module: dict[Path, set[str]] = {}
    for file in files:
        if file.suffix == ".go":
            module = _nearest(file, root, ("go.mod",))
            if module:
                package = file.parent.relative_to(module).as_posix()
                by_module.setdefault(module, set()).add("./" + package if package != "." else ".")
    return [Plan("go test", ["go", "test", *sorted(packages)], module) for module, packages in by_module.items()]


def plans_for(files: list[Path], root: Path) -> list[Plan]:
    return _python_plans(files, root) + _js_plans(files, root) + _go_plans(files, root)


# --- Hook -------------------------------------------------------------------------


def _edited(event: Event, state: State) -> list[Path]:
    root = project_root(event.cwd)
    files = []
    for raw in state.load().get("edited", []):
        path = Path(raw)
        if path.exists() and is_within(path, root):
            relative = path.relative_to(root).parts[:-1]
            if not any(part in SKIP_DIRS for part in relative):
                files.append(path)
    return files


def record(event: Event) -> Outcome:
    raw = event.tool_input.get("file_path") or event.tool_input.get("notebook_path")
    if not raw:
        return Outcome()
    path = Path(str(raw))
    path = path if path.is_absolute() else event.cwd / path
    state = State(event.session_id, "affected-tests")
    data = state.load()
    edited = data.get("edited", [])
    if str(path) not in edited:
        edited.append(str(path))
        data["edited"] = edited
        state.save(data)
    return Outcome()


def run_tests(event: Event) -> Outcome:
    state = State(event.session_id, "affected-tests")
    files = _edited(event, state)
    if not files:
        state.clear()
        return Outcome()
    plans = plans_for(files, project_root(event.cwd))
    budget = float(event.config.get("affected-tests", "timeout", TIMEOUT))
    deadline = time.monotonic() + budget
    failures: list[str] = []
    timeouts: list[str] = []
    plain = Style(enabled=False)
    for plan in plans:
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            timeouts.append(f"{plan.label} (not started: {budget:g}s budget used)")
            continue
        try:
            done = runq.execute(plan.command, cwd=plan.cwd, timeout=remaining)
        except OSError:
            continue
        if done.timed_out:
            timeouts.append(f"{plan.label} timed out after {remaining:.0f}s (log: {done.log_path})")
        elif done.exit_code not in plan.ok_codes:
            digest = runq.summarise(plan.command, done.output, done.exit_code, done.log_path, plain)
            failures.append(f"$ {' '.join(plan.command)}  (in {plan.cwd})\n{digest}")
    if failures and not event.data.get("stop_hook_active"):
        reason = "affected-tests: tests related to the files edited in this turn fail.\n\n" + "\n\n".join(failures)
        if len(reason) > MAX_REASON:
            reason = reason[:MAX_REASON] + "\n… (truncated; see the logs above)"
        return Outcome.json({"decision": "block", "reason": reason})
    state.clear()
    notes = []
    if failures:
        notes.append(f"affected-tests: {len(failures)} test run(s) still fail after a retry; see `ctk runq` logs")
    notes += [f"affected-tests: {text}" for text in timeouts]
    return Outcome.message("\n".join(notes)) if notes else Outcome()


def handle(event: Event) -> Outcome:
    if event.name == "Stop":
        return run_tests(event)
    if event.name == "PostToolUse":
        return record(event)
    return Outcome()
