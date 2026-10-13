"""``ctk map``: a compact map of a repository, so Claude reads less to find its way.

Lists source files with their main symbols (classes, functions, methods with
short signatures), ranked by how often each name is used across the project
and cut to a line budget; tests, docs and other files are summarised per
directory. ``--uses NAME`` lists where a symbol is defined and used, and which
tests touch it.

Python is parsed with ``ast``; JavaScript/TypeScript, Go, Rust, GDScript,
Java and Kotlin are scanned with line patterns. Nothing is executed.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_BUDGET = 120
LINE_WIDTH = 160
MAX_FILE_BYTES = 512 * 1024
MAX_USES = 40
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target", "vendor", ".godot", ".import",
    ".next", ".cache", "coverage", ".tox", ".mypy_cache", ".ruff_cache", ".pytest_cache",
}  # fmt: skip
SOURCE_SUFFIXES = {".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".go", ".rs", ".gd",
                   ".java", ".kt", ".kts", ".vue", ".svelte"}  # fmt: skip
DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt", ".adoc"}
ENTRY_NAMES = {"main.py", "__main__.py", "cli.py", "app.py", "manage.py", "index.ts", "index.js", "main.ts",
               "main.go", "main.rs", "lib.rs", "Main.java", "Main.kt"}  # fmt: skip
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class Symbol:
    name: str
    kind: str  # class, function, method, type, const
    line: int
    signature: str


@dataclass
class FileEntry:
    path: str
    symbols: list[Symbol] = field(default_factory=list)
    score: float = 0.0


# --- Files ------------------------------------------------------------------------


def list_files(root: Path) -> list[Path]:
    """Tracked and untracked-but-not-ignored files (git), else a filtered walk."""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            capture_output=True, timeout=30, check=False,
        )  # fmt: skip
        if done.returncode == 0:
            names = [n for n in done.stdout.decode(errors="replace").split("\0") if n]
            return sorted(root / n for n in names if not set(Path(n).parts[:-1]) & SKIP_DIRS)
    except (OSError, subprocess.TimeoutExpired):
        pass
    found = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        found += [Path(directory) / name for name in files]
    return sorted(found)


def kind_of(path: Path) -> str:
    parts = {part.lower() for part in path.parts[:-1]}
    name = path.name.lower()
    if (parts & {"tests", "test", "__tests__", "spec", "specs"} or name.startswith("test_")
            or re.search(r"(_test\.go|\.test\.[jt]sx?|\.spec\.[jt]sx?|_test\.py)$", name)):  # fmt: skip
        return "test"
    if path.suffix in SOURCE_SUFFIXES:
        return "source"
    if path.suffix.lower() in DOC_SUFFIXES or "docs" in parts:
        return "doc"
    return "other"


def _read(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:4096]:
        return None
    return data.decode("utf-8", errors="replace")


# --- Symbols ---------------------------------------------------------------------------


def _short(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _py_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    names = [a.arg for a in node.args.posonlyargs + node.args.args if a.arg not in ("self", "cls")]
    if node.args.vararg:
        names.append("*" + node.args.vararg.arg)
    elif node.args.kwonlyargs:
        names.append("*")
    names += [a.arg for a in node.args.kwonlyargs]
    if node.args.kwarg:
        names.append("**" + node.args.kwarg.arg)
    return ", ".join(names)


def python_symbols(text: str) -> list[Symbol]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    symbols = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not node.name.startswith("__"):
            symbols.append(Symbol(node.name, "function", node.lineno, _short(f"{node.name}({_py_args(node)})")))
        elif isinstance(node, ast.ClassDef):
            methods = [
                item.name for item in node.body
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and not item.name.startswith("_")
            ]  # fmt: skip
            inner = f"({', '.join(methods[:6])}{', …' if len(methods) > 6 else ''})" if methods else ""
            symbols.append(Symbol(node.name, "class", node.lineno, _short(f"class {node.name}{inner}", 90)))
    return symbols


LINE_PATTERNS: dict[str, list[tuple[re.Pattern, str]]] = {
    "js": [
        (re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*(\([^)]*\))?"), "function"),
        (re.compile(r"^(?:async\s+)?function\s*\*?\s*(\w+)\s*(\([^)]*\))?"), "function"),
        (re.compile(r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)"), "class"),
        (re.compile(r"^export\s+(?:declare\s+)?(?:interface|type|enum)\s+(\w+)"), "type"),
        (re.compile(r"^export\s+const\s+(\w+)\s*(?::[^=]+)?=\s*(?:async\s*)?(\([^)]*\))?"), "const"),
    ],
    "go": [
        (re.compile(r"^func\s+(?:\([^)]*\)\s*)?(\w+)\s*(\([^)]*\))"), "function"),
        (re.compile(r"^type\s+(\w+)\s+(?:struct|interface)"), "type"),
    ],
    "rust": [
        (re.compile(r"^\s{0,4}pub(?:\([^)]*\))?\s+(?:async\s+|const\s+|unsafe\s+)*fn\s+(\w+)\s*(\([^)]*\))?"),
         "function"),
        (re.compile(r"^pub(?:\([^)]*\))?\s+(?:struct|enum|trait|type)\s+(\w+)"), "type"),
        (re.compile(r"^fn\s+(main)\s*(\(\))"), "function"),
    ],
    "gd": [
        (re.compile(r"^class_name\s+(\w+)"), "class"),
        (re.compile(r"^(?:static\s+)?func\s+(\w+)\s*(\([^)]*\))"), "function"),
        (re.compile(r"^signal\s+(\w+)"), "const"),
    ],
    "jvm": [
        (re.compile(r"^(?:(?:public|internal|data|abstract|sealed|open)\s+)*"
                    r"(?:class|interface|object|enum|record)\s+(\w+)"), "class"),
        (re.compile(r"^\s{0,4}(?:(?:public|internal|override|suspend)\s+)*fun\s+(\w+)\s*(\([^)]*\))?"),
         "function"),
        (re.compile(r"^\s{4}public\s+(?:static\s+)?[\w<>\[\],\s]+?\s(\w+)\s*(\([^)]*\))"), "function"),
    ],
}  # fmt: skip
FAMILY = {".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js", ".mts": "js",
          ".cts": "js", ".vue": "js", ".svelte": "js", ".go": "go", ".rs": "rust", ".gd": "gd",
          ".java": "jvm", ".kt": "jvm", ".kts": "jvm"}  # fmt: skip


def text_symbols(text: str, family: str) -> list[Symbol]:
    symbols, seen = [], set()
    for number, line in enumerate(text.splitlines(), 1):
        for pattern, kind in LINE_PATTERNS[family]:
            match = pattern.match(line)
            if not match or match.group(1) in seen:
                continue
            name = match.group(1)
            seen.add(name)
            args = match.group(2) if pattern.groups >= 2 and match.group(2) else ""
            label = f"{'class ' if kind == 'class' else ''}{name}{_short(args, 50) if args else ''}"
            symbols.append(Symbol(name, kind, number, label))
            break
    return symbols


def symbols_for(path: Path, text: str) -> list[Symbol]:
    if path.suffix in (".py", ".pyi"):
        return python_symbols(text)
    family = FAMILY.get(path.suffix)
    return text_symbols(text, family) if family else []


# --- Map -----------------------------------------------------------------------------------


@dataclass
class RepoMap:
    root: str
    files: list[FileEntry]
    collapsed: dict[str, dict[str, int]]  # directory -> {"tests": n, "docs": n, "other": n}
    total_files: int
    total_symbols: int


def _rollup(directory: str, source_dirs: set[str]) -> str:
    """Directories without source code are summarised under their top-level directory."""
    if directory == "." or directory in source_dirs:
        return directory
    return Path(directory).parts[0]


def build(root: Path) -> RepoMap:
    files = list_files(root)
    seen_in: Counter = Counter()  # name -> number of files that mention it
    entries: list[FileEntry] = []
    others: list[tuple[str, str]] = []  # (directory, bucket)
    for path in files:
        relative = path.relative_to(root)
        kind = kind_of(relative)
        directory = str(relative.parent)
        if kind in ("source", "test"):
            text = _read(path)
            if text is not None:
                seen_in.update(set(WORD.findall(text)))
                if kind == "source":
                    entries.append(FileEntry(str(relative), symbols_for(path, text)))
                    continue
        others.append((directory, {"test": "tests", "doc": "docs"}.get(kind, "other")))
    source_dirs = {str(Path(e.path).parent) for e in entries}
    collapsed: dict[str, Counter] = {}
    for directory, bucket in others:
        collapsed.setdefault(_rollup(directory, source_dirs), Counter())[bucket] += 1
    defined_in: Counter = Counter(s.name for e in entries for s in {x.name: x for x in e.symbols}.values())

    def centrality(name: str) -> float:
        # Mentioned by many files, defined by few: `findById` in fifteen repositories is not central.
        return max(0, seen_in[name] - defined_in[name]) / max(1, defined_in[name])

    for entry in entries:
        public = [s for s in entry.symbols if not s.name.startswith("_")] or entry.symbols
        public.sort(key=lambda s: (-centrality(s.name), s.line))
        entry.symbols = public
        entry.score = sum(centrality(s.name) for s in public[:5])
        entry.score += 25 if Path(entry.path).name in ENTRY_NAMES else 0
    return RepoMap(
        root=str(root),
        files=entries,
        collapsed={d: dict(c) for d, c in sorted(collapsed.items())},
        total_files=len(files),
        total_symbols=sum(len(e.symbols) for e in entries),
    )


def _home(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home) :] if path == home or path.startswith(home + os.sep) else path


def render(repo: RepoMap, budget: int = DEFAULT_BUDGET) -> str:
    """Directories with their best files and symbols, within ``budget`` lines."""
    header = (f"map: {_home(repo.root)} · {repo.total_files} files · {len(repo.files)} source · "
              f"{repo.total_symbols} symbols")  # fmt: skip
    by_score = sorted(repo.files, key=lambda e: (-e.score, e.path))
    dirs_of = {e.path: str(Path(e.path).parent) for e in repo.files}
    # Breadth first: the best file of every directory, then the rest by score.
    firsts: dict[str, FileEntry] = {}
    for entry in by_score:
        firsts.setdefault(dirs_of[entry.path], entry)
    ranked = list(firsts.values()) + [e for e in by_score if firsts[dirs_of[e.path]] is not e]
    # Lines needed: one per shown file, one per directory heading, one per directory with collapsed files.
    chosen: list[FileEntry] = []
    for entry in ranked:
        directories = {dirs_of[e.path] for e in [*chosen, entry]}
        needed = len(chosen) + 1 + len(directories) + len(repo.collapsed) + 2
        if needed > budget:
            break
        chosen.append(entry)
    shown = {e.path for e in chosen}
    by_dir: dict[str, list[FileEntry]] = {}
    for entry in chosen:
        by_dir.setdefault(dirs_of[entry.path], []).append(entry)
    omitted: Counter = Counter(dirs_of[e.path] for e in repo.files if e.path not in shown)
    directories = sorted(set(by_dir) | set(repo.collapsed) | set(omitted))
    lines = [header]
    for directory in directories:
        label = "./" if directory == "." else directory.rstrip("/") + "/"
        extras = []
        counts = repo.collapsed.get(directory, {})
        for bucket in ("tests", "docs", "other"):
            if counts.get(bucket):
                extras.append(f"{counts[bucket]} {bucket}")
        if omitted.get(directory):
            extras.append(f"{omitted[directory]} more source")
        if not by_dir.get(directory) and not extras:
            continue
        lines.append(label + (f"  ({', '.join(extras)})" if extras else ""))
        for entry in by_dir.get(directory, []):
            name = Path(entry.path).name
            symbols = " · ".join(s.signature for s in entry.symbols)
            line = f"  {name}" + (f"  {symbols}" if symbols else "")
            lines.append(line if len(line) <= LINE_WIDTH else line[: LINE_WIDTH - 1] + "…")
    hidden = len(repo.files) - len(chosen)
    if hidden:
        lines.append(f"({hidden} less-used source files not shown; --budget {budget * 2} shows more)")
    return "\n".join(lines)


# --- Uses -------------------------------------------------------------------------------------


@dataclass
class Use:
    path: str
    line: int
    text: str
    kind: str  # definition, source, test, doc, other


DEFINITION = (
    r"^\s*(?:export\s+)?(?:default\s+)?(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?"
    r"(?:def|class|function|func|fn|type|interface|struct|enum|trait|const|let|var|signal|class_name)\s+"
    r"(?:\([^)]*\)\s*)?{name}\b"
)


def find_uses(root: Path, name: str) -> list[Use]:
    word = re.compile(rf"\b{re.escape(name)}\b")
    definition = re.compile(DEFINITION.format(name=re.escape(name)))
    uses = []
    for path in list_files(root):
        text = _read(path)
        if not text or name not in text:
            continue
        relative = path.relative_to(root)
        kind = kind_of(relative)
        for number, line in enumerate(text.splitlines(), 1):
            if word.search(line):
                is_definition = kind in ("source", "test") and definition.search(line)
                uses.append(
                    Use(str(relative), number, _short(line.strip(), 110), "definition" if is_definition else kind)
                )
    order = {"definition": 0, "source": 1, "test": 2, "doc": 3, "other": 4}
    return sorted(uses, key=lambda u: (order[u.kind], u.path, u.line))


def render_uses(root: Path, name: str, uses: list[Use]) -> str:
    if not uses:
        return f"map: {name}: no uses found under {_home(str(root))}"
    counts = Counter(u.kind for u in uses)
    summary = ", ".join(f"{counts[k]} {k}" for k in ("definition", "source", "test", "doc", "other") if counts[k])
    lines = [f"map: {name} · {summary}"]
    for use in uses[:MAX_USES]:
        lines.append(f"  {use.path}:{use.line}  [{use.kind}] {use.text}")
    if len(uses) > MAX_USES:
        lines.append(f"  … {len(uses) - MAX_USES} more")
    tests = sorted({u.path for u in uses if u.kind == "test"})
    defined = sorted({u.path for u in uses if u.kind == "definition" and u.path.endswith(".py")})
    if defined:
        from .hooks.affected_tests import python_tests

        mapped = python_tests([root / p for p in defined], root)
        tests = sorted(set(tests) | {str(t.relative_to(root)) for t in mapped})
    lines.append("tests: " + (", ".join(tests) if tests else "none reference it"))
    return "\n".join(lines)


def run(args) -> int:
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"map: not a directory: {root}", file=sys.stderr)
        return 1
    if args.uses:
        uses = find_uses(root, args.uses)
        if args.json:
            print(json.dumps([asdict(u) for u in uses], indent=2))
        else:
            print(render_uses(root, args.uses, uses))
        return 0 if uses else 1
    repo = build(root)
    print(json.dumps(asdict(repo), indent=2) if args.json else render(repo, args.budget))
    return 0
