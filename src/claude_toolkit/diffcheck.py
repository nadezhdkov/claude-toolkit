"""``ctk diffcheck``: deterministic checks of a change, before a model reviews it.

Compares the working tree (uncommitted and untracked changes included) with a
base (default: the merge-base with the default branch) and reports, with
``file:line`` where it applies:

- public symbols removed or with a changed signature, and where removed ones
  are still used (``ctk map`` extraction before and after);
- lockfiles, dependency manifests, CI, container and environment files,
  generated, large and binary files that changed;
- debug leftovers and new TODO/FIXME markers in added lines;
- source changes without test changes.

No model, no network; the ``reviewer`` agent starts from this output.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .map import find_uses, kind_of, symbols_for

LARGE_FILE = 512 * 1024
LEVELS = ("high", "warn", "info")
LOCKFILES = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "poetry.lock", "Pipfile.lock",
             "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock")  # fmt: skip
MANIFESTS = ("pyproject.toml", "package.json", "Cargo.toml", "go.mod", "requirements*.txt", "Gemfile",
             "composer.json", "build.gradle*", "pom.xml")  # fmt: skip
ROOT_MANIFESTS = ("setup.py", "setup.cfg")  # only at the root: src/pkg/setup.py is just a module
SENSITIVE = (".github/workflows/*", ".gitlab-ci.yml", "Dockerfile*", "docker-compose*.yml", "compose*.yaml",
             ".env*", "*.pem", "*.key", "Makefile", ".pre-commit-config.yaml")  # fmt: skip
GENERATED = ("*.min.js", "*.min.css", "*_pb2.py", "*.pb.go", "*.generated.*", "dist/*", "build/*")
JS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte")
# Only shapes that are almost always leftovers: CLI output and logging are legitimate.
DEBUG = [
    (re.compile(r"^\s*(?:import i?pdb\b|from i?pdb import|breakpoint\(\)|i?pdb\.set_trace\(\))"),
     "debugger left in", (".py",)),
    (re.compile(r"^\s*print\((?:f?[\"'](?:debug|here|>>>|\*\*\*|---)|[^)]*=\}|repr\()", re.I), "debug print", (".py",)),
    # A bare variable is a leftover in library code, normal output in a command-line program.
    (re.compile(r"^\s*print\([A-Za-z_][\w.\[\]]*\)\s*$"), "print of a variable", (".py",)),
    (re.compile(r"^\s*console\.(?:log|debug)\("), "console.log", JS),
    (re.compile(r"^\s*debugger;?\s*$"), "debugger statement", JS),
    (re.compile(r"\bdbg!\("), "dbg! macro", (".rs",)),
    (re.compile(r"^\s*print(?:_debug)?\((?:[\"'](?:debug|here)|[A-Za-z_]\w*\)\s*$)", re.I), "debug print", (".gd",)),
    (re.compile(r"(?:#|//|/\*|--)\s*(?:TODO|FIXME|XXX|HACK)\b"), "new TODO/FIXME", ()),
]  # fmt: skip


@dataclass
class Finding:
    level: str
    kind: str
    path: str
    line: int | None
    message: str


def _git(root: Path, *args: str, check: bool = False) -> str:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, errors="replace", timeout=60)
    if check and done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"git {' '.join(args)} failed")
    return done.stdout if done.returncode == 0 else ""


def default_base(root: Path) -> str:
    """The merge-base with the default branch, or HEAD when on it."""
    for ref in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
        base = _git(root, "merge-base", "HEAD", ref).strip()
        if base:
            head = _git(root, "rev-parse", "HEAD").strip()
            return base if base != head else "HEAD"
    return "HEAD"


@dataclass
class Change:
    path: str
    status: str  # A, M, D, R
    added: list[tuple[int, str]]  # (line in the new file, text)
    old_path: str | None = None
    binary: bool = False


def changes(root: Path, base: str) -> list[Change]:
    result: dict[str, Change] = {}
    for line in _git(root, "diff", "--name-status", "-M", base).splitlines():
        parts = line.split("\t")
        status = parts[0][0]
        path = parts[-1]
        result[path] = Change(path, status, [], parts[1] if status == "R" else None)
    for path in _git(root, "ls-files", "--others", "--exclude-standard").splitlines():
        result[path] = Change(path, "A", [])
    for path in _binary_paths(root, base):
        if path in result:
            result[path].binary = True
    diff = _git(root, "diff", "-U0", "--no-color", "-M", base)
    current, line_no = None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:]
            current = result.get(name[2:]) if name.startswith("b/") else None
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            line_no = int(match.group(1)) if match else 0
        elif current is not None and line.startswith("+") and not line.startswith("+++"):
            current.added.append((line_no, line[1:]))
            line_no += 1
    for change in result.values():
        if change.status == "A" and not change.added and not change.binary:
            path = root / change.path
            try:
                if path.stat().st_size <= LARGE_FILE:
                    text = path.read_text(errors="replace")
                    change.added = list(enumerate(text.splitlines(), 1))
            except (OSError, UnicodeDecodeError):
                pass
    return sorted(result.values(), key=lambda c: c.path)


def _binary_paths(root: Path, base: str) -> list[str]:
    """Git reports binary files with `-` for both line counts."""
    paths = []
    for line in _git(root, "diff", "--numstat", base).splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] == "-" and parts[1] == "-":
            paths.append(parts[2])
    return paths


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    name = Path(path).name
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(path, p) for p in patterns)


# --- Checks ---------------------------------------------------------------------------------


def api_findings(root: Path, base: str, change: Change) -> list[Finding]:
    if kind_of(Path(change.path)) != "source" or change.status == "A":
        return []
    old_text = _git(root, "show", f"{base}:{change.old_path or change.path}")
    if not old_text:
        return []
    path = root / change.path
    new_text = "" if change.status == "D" else (path.read_text(errors="replace") if path.exists() else "")
    before = {s.name: s for s in symbols_for(path, old_text) if not s.name.startswith("_")}
    after = {s.name: s for s in symbols_for(path, new_text) if not s.name.startswith("_")}
    findings = []
    for name, old in before.items():
        if name not in after:
            users = [use for use in find_uses(root, name) if use.kind in ("source", "test") and use.path != change.path]
            files = sorted({u.path for u in users})
            if files:
                where = ", ".join(f"{u.path}:{u.line}" for u in users[:3]) + (" …" if len(users) > 3 else "")
                message = f"removed `{name}` is still used in {len(files)} file(s): {where}"
                findings.append(Finding("high", "api", change.path, old.line, message))
            else:
                findings.append(Finding("warn", "api", change.path, old.line, f"public `{name}` removed"))
        elif after[name].signature != old.signature:
            findings.append(Finding("warn", "api", change.path, after[name].line,
                                    f"signature changed: {old.signature} → {after[name].signature}"))  # fmt: skip
    return findings


def file_findings(root: Path, change: Change) -> list[Finding]:
    path, findings = change.path, []
    if _matches(path, LOCKFILES):
        findings.append(
            Finding("warn", "dependencies", path, None, "lockfile changed: check what was added or upgraded")
        )
    elif _matches(path, MANIFESTS) or ("/" not in path and _matches(path, ROOT_MANIFESTS)):
        findings.append(Finding("warn", "dependencies", path, None, "dependency manifest changed"))
    if _matches(path, SENSITIVE):
        level = "high" if Path(path).name.startswith(".env") and not path.endswith(".example") else "warn"
        findings.append(Finding(level, "config", path, None, "CI, container, build or environment file changed"))
    if _matches(path, GENERATED):
        findings.append(
            Finding("warn", "generated", path, None, "generated file changed: regenerate it instead of editing")
        )
    full = root / path
    if change.binary:
        findings.append(Finding("warn", "binary", path, None, "binary file changed"))
    elif change.status != "D" and full.exists() and full.stat().st_size > LARGE_FILE:
        findings.append(Finding("warn", "large", path, None, f"large file ({full.stat().st_size // 1024} KiB)"))
    return findings


def debug_findings(root: Path, change: Change) -> list[Finding]:
    suffix = Path(change.path).suffix
    if kind_of(Path(change.path)) == "doc":
        return []
    findings = []
    is_test = kind_of(Path(change.path)) == "test"
    try:
        whole = (root / change.path).read_text(errors="replace")
    except OSError:
        whole = "\n".join(text for _, text in change.added)
    is_program = "argparse" in whole or "__main__" in whole or "sys.argv" in whole
    for number, text in change.added:
        for pattern, label, suffixes in DEBUG:
            if suffixes and suffix not in suffixes:
                continue
            if (is_test and label in ("debug print", "print of a variable", "console.log")) or (
                is_program and label == "print of a variable"
            ):
                continue
            if pattern.search(text):
                level = "info" if label == "new TODO/FIXME" else "warn"
                findings.append(Finding(level, "debug", change.path, number, f"{label}: {text.strip()[:100]}"))
                break
    return findings


def test_findings(root: Path, all_changes: list[Change]) -> list[Finding]:
    sources = [c for c in all_changes if kind_of(Path(c.path)) == "source" and c.status != "D" and c.added]
    tests = {c.path for c in all_changes if kind_of(Path(c.path)) == "test"}
    if not sources:
        return []
    if not tests:
        names = ", ".join(c.path for c in sources[:3]) + (" …" if len(sources) > 3 else "")
        return [Finding("warn", "tests", sources[0].path, None, f"source changed without any test change: {names}")]
    from .hooks.affected_tests import python_tests

    findings = []
    for change in sources:
        if change.path.endswith(".py"):
            mapped = {str(p.relative_to(root)) for p in python_tests([root / change.path], root)}
            if mapped and not mapped & tests:
                findings.append(Finding("info", "tests", change.path, None,
                                        f"its tests were not changed: {', '.join(sorted(mapped))}"))  # fmt: skip
    return findings


def check(root: Path, base: str) -> tuple[list[Change], list[Finding]]:
    found = changes(root, base)
    findings: list[Finding] = []
    for change in found:
        findings += api_findings(root, base, change)
        findings += file_findings(root, change)
        if change.status != "D":
            findings += debug_findings(root, change)
    findings += test_findings(root, found)
    findings.sort(key=lambda f: (LEVELS.index(f.level), f.kind, f.path, f.line or 0))
    return found, findings


def render(root: Path, base: str, found: list[Change], findings: list[Finding]) -> str:
    added = sum(len(c.added) for c in found)
    counts = {level: sum(1 for f in findings if f.level == level) for level in LEVELS}
    lines = [f"diffcheck: {len(found)} file(s) changed, {added} line(s) added since {base[:12]} · "
             + " · ".join(f"{counts[level]} {level}" for level in LEVELS)]  # fmt: skip
    for finding in findings:
        where = f"{finding.path}:{finding.line}" if finding.line else finding.path
        lines.append(f"  {finding.level:<4}  [{finding.kind}] {where}  {finding.message}")
    if not findings:
        lines.append("  nothing to flag")
    return "\n".join(lines)


def run(args) -> int:
    root = Path(args.path).expanduser().resolve()
    top = _git(root, "rev-parse", "--show-toplevel").strip()
    if not top:
        print("diffcheck: not inside a git repository", file=sys.stderr)
        return 1
    root = Path(top)
    base = args.base or default_base(root)
    try:
        _git(root, "rev-parse", "--verify", base, check=True)
    except RuntimeError as error:
        print(f"diffcheck: unknown base {base!r}: {error}", file=sys.stderr)
        return 1
    found, findings = check(root, base)
    if args.json:
        print(json.dumps({"base": base, "files": len(found), "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        print(render(root, base, found, findings))
    return 1 if any(f.level == "high" for f in findings) or (args.strict and findings) else 0
