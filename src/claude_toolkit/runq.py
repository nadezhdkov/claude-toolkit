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
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .style import Spinner, Style, shorten_home

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
    digest.summary = _collect(
        lines,
        re.compile(
            r"^=+ .*(passed|failed|error|skipped|no tests ran).* =+$|^\d+ (passed|failed|errors?)\b.* in [\d.]+s"
        ),
    )
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


def summarise(
    command: list[str],
    output: str,
    exit_code: int,
    log_path: Path | None,
    style: Style | None = None,
    elapsed: float | None = None,
) -> str:
    """Render what to show for one finished command."""
    st = style or Style.detect()
    text = ANSI.sub("", output)
    lines = text.splitlines()
    if st.enabled:
        return _summarise_styled(command, lines, exit_code, log_path, st, elapsed)
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


_FAIL_WORD = re.compile(
    r"(FAILED|ERROR|FAIL|--- FAIL|error(?:\[E\d+\])?|error TS\d+|panic|\u00d7|\u2717|\u2715|\u25cf)"
)
_COUNT = re.compile(r"(\d+ (?:failed|errors?|problems?))|(\d+ passed)|(\d+ (?:skipped|warnings?))")


def _paint_failure(line: str, st: Style) -> str:
    return _FAIL_WORD.sub(lambda m: st.err(m.group(0), bold=True), line, count=1)


def _paint_summary(line: str, st: Style) -> str:
    def color(match: re.Match) -> str:
        if match.group(1):
            return st.err(match.group(0), bold=True)
        if match.group(2):
            return st.ok(match.group(0), bold=True)
        return st.warn(match.group(0), bold=True)

    return st.bold(_COUNT.sub(color, line)) if _COUNT.search(line) else st.bold(line)


def _summarise_styled(
    command: list[str], lines: list[str], exit_code: int, log_path: Path | None, st: Style, elapsed: float | None
) -> str:
    out = [st.header("ctk runq", " ".join(command)), ""]
    if len(lines) <= SHORT_OUTPUT_LINES:
        digest = digest_output(command, lines)
        failures, summary = set(digest.failures), set(digest.summary)
        for line in lines:
            if line in failures:
                out.append(f"  {_paint_failure(line, st)}")
            elif line in summary:
                out.append(f"  {_paint_summary(line, st)}")
            else:
                out.append(f"  {line}")
    else:
        digest = digest_output(command, lines)
        out.append(f"  {st.accent(f'[{digest.tool}]', bold=True)}")
        failures = digest.failures[:MAX_FAILURE_LINES]
        out.extend(f"  {_paint_failure(line, st)}" for line in failures)
        hidden = len(digest.failures) - len(failures)
        if hidden > 0:
            out.append(f"  {st.muted(f'… {hidden} more failure line(s) in the log')}")
        if digest.failure_count is not None and digest.failure_count != len(failures):
            out.append(f"  {st.muted(f'failures counted: {digest.failure_count}')}")
        out.extend(f"  {_paint_summary(line, st)}" for line in digest.summary[-5:])
        if exit_code != 0 and not failures:
            out.append(f"  {st.muted(f'── last {TAIL_LINES} lines ' + '─' * 30)}")
            out.extend(f"  {line}" for line in lines[-TAIL_LINES:])
        elif exit_code == 0 and not digest.summary:
            out.extend(f"  {line}" for line in lines[-5:])
    status = st.ok(f"✓ exit {exit_code}", bold=True) if exit_code == 0 else st.err(f"✗ exit {exit_code}", bold=True)
    facts = [f"{len(lines)} lines"] + ([f"{elapsed:.1f}s"] if elapsed is not None else [])
    out += ["", f"  {status} {st.muted('· ' + ' · '.join(facts))}"]
    if log_path:
        out.append(f"  {st.muted('log')} {st.accent2(shorten_home(log_path))}")
    return "\n".join(out)


@dataclass
class Execution:
    exit_code: int
    output: str
    log_path: Path
    elapsed: float
    timed_out: bool = False


def execute(
    command: list[str], *, cwd: Path | None = None, timeout: float | None = None, keep_logs: int = 50
) -> Execution:
    """Run ``command``, writing its full output to a new log. Raises FileNotFoundError."""
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(command[0]).name)[:40]
    log_path, log = _new_log(directory, f"{time.strftime('%Y%m%d-%H%M%S')}-{name}")
    started = time.monotonic()
    timed_out = False
    with log:
        log.write(f"$ {' '.join(command)}\n")
        process = subprocess.Popen(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"
        )
        timer = None
        if timeout is not None:

            def kill() -> None:
                nonlocal timed_out
                timed_out = True
                process.kill()

            timer = threading.Timer(timeout, kill)
            timer.start()
        chunks: list[str] = []
        assert process.stdout is not None
        try:
            for line in process.stdout:
                log.write(line)
                chunks.append(line)
            exit_code = process.wait()
        finally:
            if timer is not None:
                timer.cancel()
            if process.poll() is None:
                process.kill()
    _prune(directory, keep_logs)
    return Execution(exit_code, "".join(chunks), log_path, time.monotonic() - started, timed_out)


def _new_log(directory: Path, stem: str):
    """Create a log that no other run uses: commands started in the same second get -2, -3…"""
    for index in range(1, 1000):
        path = directory / (f"{stem}.log" if index == 1 else f"{stem}-{index}.log")
        try:
            return path, path.open("x", encoding="utf-8", errors="replace")
        except FileExistsError:
            continue
    raise FileExistsError(f"too many logs named {stem} in {directory}")


def run(command: list[str], *, keep_logs: int = 50) -> int:
    if not command:
        print("usage: ctk runq -- <command> [args...]", file=sys.stderr)
        return 2
    try:
        with Spinner(f"running {' '.join(command)}"):
            done = execute(command, keep_logs=keep_logs)
    except FileNotFoundError:
        print(f"runq: command not found: {command[0]}", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        return 130
    print(summarise(command, done.output, done.exit_code, done.log_path, elapsed=done.elapsed))
    return done.exit_code


def _prune(directory: Path, keep: int) -> None:
    logs = sorted(directory.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in logs[keep:]:
        old.unlink(missing_ok=True)
