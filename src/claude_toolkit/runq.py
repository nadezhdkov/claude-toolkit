"""``ctk runq``: run a command, keep its full output in a log, print what matters.

Short output is printed unchanged. Long output is reduced to the failures and
summary that tool-specific extractors recognise, with a pointer to the full
log. The command's exit code is always preserved.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

SHORT_OUTPUT_LINES = 60
MAX_FAILURE_LINES = 50
TAIL_LINES = 40
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def log_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "claude-toolkit" / "runq"


@dataclass
class Digest:
    tool: str
    failures: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)
    failure_count: int | None = None


def _collect(lines: list[str], pattern: re.Pattern, limit: int | None = None) -> list[str]:
    seen: list[str] = []
    for line in lines:
        if pattern.search(line) and line not in seen:
            seen.append(line.rstrip())
            if limit and len(seen) >= limit:
                break
    return seen


def _pytest(lines: list[str]) -> Digest:
    digest = Digest("pytest")
    failed = re.compile(r"^(FAILED|ERROR) \S")
    digest.failures = [line.rstrip() for line in lines if failed.match(line)]
    digest.failure_count = len(digest.failures)
    digest.summary = _collect(lines, re.compile(r"^=+ .*(passed|failed|error|skipped|no tests ran).* =+$"))
    if not digest.failures:
        digest.failures = _collect(lines, re.compile(r"^E\s+|^_{3,} .* _{3,}$"), MAX_FAILURE_LINES)
    return digest


def _js_test(lines: list[str]) -> Digest:
    digest = Digest("vitest/jest")
    digest.failures = _collect(lines, re.compile(r"^\s*(FAIL\s|\u00d7|\u2717|\u2715|\u25cf\s)"))
    digest.failure_count = len(digest.failures)
    digest.summary = _collect(lines, re.compile(r"^\s*(Test Files|Tests|Test Suites|Snapshots|Duration|Time):?\s"))
    return digest


def _tsc(lines: list[str]) -> Digest:
    digest = Digest("tsc")
    digest.failures = _collect(lines, re.compile(r"error TS\d+:"))
    digest.failure_count = len(digest.failures)
    digest.summary = _collect(lines, re.compile(r"^Found \d+ errors?"))
    return digest


def _lint(lines: list[str]) -> Digest:
    digest = Digest("linter")
    digest.failures = _collect(
        lines, re.compile(r"^\S+:\d+:\d+:?\s|^\s+\d+:\d+\s+(error|warning)\s|^\s*-->\s\S+:\d+:\d+")
    )
    digest.failure_count = len(digest.failures)
    digest.summary = _collect(lines, re.compile(r"^(Found \d+ error|✖ \d+ problem|\d+ problems?|All checks passed)"))
    return digest


def _cargo(lines: list[str]) -> Digest:
    digest = Digest("cargo")
    digest.failures = _collect(
        lines, re.compile(r"^(error(\[E\d+\])?:|warning: unused|test \S+ \.\.\. FAILED|---- \S+ stdout ----)")
    )
    digest.failures += [line for line in _collect(lines, re.compile(r"^\s+-->\s")) if line not in digest.failures]
    digest.failure_count = sum(1 for line in digest.failures if line.startswith(("error", "test ")))
    digest.summary = _collect(lines, re.compile(r"^(test result:|error: could not compile|Finished )"))
    return digest


def _go(lines: list[str]) -> Digest:
    digest = Digest("go test")
    digest.failures = _collect(lines, re.compile(r"^\s*--- FAIL:|^\S+\.go:\d+:|^panic:"))
    digest.failure_count = sum(1 for line in digest.failures if "--- FAIL" in line)
    digest.summary = _collect(lines, re.compile(r"^(FAIL|ok)\s+\S+"))
    return digest


def _gradle(lines: list[str]) -> Digest:
    digest = Digest("gradle")
    digest.failures = _collect(lines, re.compile(r"(FAILED$|^e: |^\S+\.(java|kt):\d+: error)"))
    digest.failure_count = len(digest.failures)
    digest.summary = _collect(lines, re.compile(r"^(BUILD (SUCCESSFUL|FAILED)|\d+ tests? completed)"))
    return digest


_GENERIC_ERROR = re.compile(r"(?i)\b(error|fail(ed|ure)?|panic|exception|traceback|fatal)\b")


def _generic(lines: list[str]) -> Digest:
    return Digest("generic", failures=_collect(lines, _GENERIC_ERROR, 30))


# (command hint, output signature, extractor)
EXTRACTORS: list[tuple[re.Pattern, re.Pattern, Callable[[list[str]], Digest]]] = [
    (re.compile(r"\bpytest\b|\bpy\.test\b"), re.compile(r"^=+ test session starts =+"), _pytest),
    (re.compile(r"\b(vitest|jest)\b"), re.compile(r"^\s*(Test Files|Test Suites):"), _js_test),
    (re.compile(r"\btsc\b"), re.compile(r"error TS\d+:"), _tsc),
    (re.compile(r"\b(ruff|eslint|flake8|oxlint|biome)\b"), re.compile(r"^\S+:\d+:\d+"), _lint),
    (re.compile(r"\bcargo\b"), re.compile(r"^\s*(Compiling|test result:|error\[E\d+\])"), _cargo),
    (re.compile(r"\bgo\s+(test|build|vet)\b"), re.compile(r"^(ok|FAIL|---)\s"), _go),
    (re.compile(r"\b(gradle|gradlew)\b"), re.compile(r"^BUILD (SUCCESSFUL|FAILED)"), _gradle),
]


def digest_output(command: list[str], lines: list[str]) -> Digest:
    """Pick an extractor from the command name, then from the output itself."""
    joined = " ".join(command)
    for hint, _signature, extractor in EXTRACTORS:
        if hint.search(joined):
            return extractor(lines)
    for _hint, signature, extractor in EXTRACTORS:
        if any(signature.search(line) for line in lines[:2000]):
            return extractor(lines)
    return _generic(lines)


def summarise(command: list[str], output: str, exit_code: int, log_path: Path | None) -> str:
    """Render what to show for one finished command."""
    text = ANSI.sub("", output)
    lines = text.splitlines()
    where = f" · log: {log_path}" if log_path else ""
    header = f"runq: exit {exit_code} · {len(lines)} lines{where}"
    if len(lines) <= SHORT_OUTPUT_LINES:
        return "\n".join([*lines, header]) if lines else header
    digest = digest_output(command, lines)
    out = [header, f"[{digest.tool}]"]
    failures = digest.failures[:MAX_FAILURE_LINES]
    if failures:
        out.extend(failures)
        hidden = len(digest.failures) - len(failures)
        if hidden > 0:
            out.append(f"… {hidden} more failure line(s) in the log")
    if digest.failure_count is not None and digest.failure_count != len(failures):
        out.append(f"failures counted: {digest.failure_count}")
    if digest.summary:
        out.extend(digest.summary[-5:])
    if exit_code != 0 and not failures:
        out.append(f"--- last {TAIL_LINES} lines ---")
        out.extend(lines[-TAIL_LINES:])
    elif exit_code == 0 and not digest.summary:
        out.extend(lines[-5:])
    return "\n".join(out)


def run(command: list[str], *, keep_logs: int = 50) -> int:
    if not command:
        print("usage: ctk runq -- <command> [args...]", file=sys.stderr)
        return 2
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(command[0]).name)[:40]
    log_path = directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}.log"
    try:
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            log.write(f"$ {' '.join(command)}\n")
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"
            )
            chunks: list[str] = []
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line)
                chunks.append(line)
            exit_code = process.wait()
    except FileNotFoundError:
        print(f"runq: command not found: {command[0]}", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        return 130
    print(summarise(command, "".join(chunks), exit_code, log_path))
    _prune(directory, keep_logs)
    return exit_code


def _prune(directory: Path, keep: int) -> None:
    logs = sorted(directory.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in logs[keep:]:
        old.unlink(missing_ok=True)
