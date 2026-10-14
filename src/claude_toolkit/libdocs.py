"""``ctk libdocs``: what a dependency really is in this project, from its installed files.

For a package name it finds the installed copy (Python ``.venv``/site-packages,
``node_modules``, the Cargo registry, the Go module cache) and reports the
installed version next to the declared constraint, the source path, the README
and the public API. ``--find SYMBOL`` prints where a symbol is defined, with
its signature and docstring, in the installed version.

Nothing is imported or executed: Python sources are parsed with ``ast``, type
declarations and Rust/Go sources are scanned as text. That keeps it fast and
safe on untrusted packages.
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from email.parser import Parser
from pathlib import Path

from .style import Style, shorten_home

API_LINES = 60
README_PREVIEW = 25
FIND_CONTEXT = 25
MAX_FILES = 5000


class NotFound(Exception):
    """The package is not installed where this ecosystem looks."""


@dataclass
class Library:
    name: str
    ecosystem: str
    version: str
    path: Path
    declared: str | None = None
    declared_in: str | None = None
    summary: str = ""
    homepage: str = ""
    readme: Path | None = None
    readme_text: str = ""
    entry: Path | None = None  # module or type declarations the API comes from
    notes: list[str] = field(default_factory=list)


@dataclass
class Definition:
    file: Path
    line: int
    text: str


# --- helpers ---------------------------------------------------------------------------


def _ancestors(start: Path) -> Iterator[Path]:
    yield start
    yield from start.parents


def _find_up(start: Path, name: str) -> Path | None:
    for directory in _ancestors(start):
        if (directory / name).exists():
            return directory / name
    return None


def _readme_in(directory: Path) -> Path | None:
    for candidate in sorted(directory.iterdir()) if directory.is_dir() else []:
        if candidate.is_file() and candidate.name.lower().startswith("readme"):
            return candidate
    return None


def _walk(root: Path, suffixes: tuple[str, ...]) -> Iterator[Path]:
    seen = 0
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "tests"))
        for name in sorted(files):
            if name.endswith(suffixes):
                seen += 1
                if seen > MAX_FILES:
                    return
                yield Path(directory) / name


def _python_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# --- Python -------------------------------------------------------------------------------


def site_packages(project: Path) -> list[Path]:
    """The project's virtual environment first, then the interpreter on PATH."""
    found: list[Path] = []
    for directory in _ancestors(project):
        for venv in (".venv", "venv", "env"):
            found += sorted((directory / venv / "lib").glob("python*/site-packages"))
        if found or (directory / ".git").exists():
            break
    if not found:
        try:
            done = subprocess.run(
                ["python3", "-c", "import json, sys; print(json.dumps(sys.path))"],
                capture_output=True, text=True, timeout=10, check=False, encoding="utf-8", errors="replace",
            )  # fmt: skip
            found = [Path(p) for p in json.loads(done.stdout or "[]") if p.endswith(("site-packages", "dist-packages"))]
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
    return [path for path in found if path.is_dir()]


def _dist_info(site: Path, name: str) -> Path | None:
    wanted = _python_name(name)
    infos = sorted(site.glob("*.dist-info"))
    for info in infos:
        if _python_name(info.name.rsplit("-", 1)[0]) == wanted:
            return info
    for info in infos:  # an import name such as `yaml` for PyYAML
        top = info / "top_level.txt"
        if top.exists() and name in top.read_text(encoding="utf-8").split():
            return info
    return None


def _python_declared(project: Path, name: str) -> tuple[str | None, str | None]:
    pyproject = _find_up(project, "pyproject.toml")
    if not pyproject:
        return None, None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None, None
    wanted = _python_name(name)
    groups = [data.get("project", {}).get("dependencies", [])]
    groups += list(data.get("project", {}).get("optional-dependencies", {}).values())
    groups += [g for g in data.get("dependency-groups", {}).values() if isinstance(g, list)]
    for requirement in (r for group in groups for r in group if isinstance(r, str)):
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
        if match and _python_name(match.group(1)) == wanted:
            return requirement.strip(), str(pyproject)
    return None, None


def find_python(project: Path, name: str) -> Library:
    for site in site_packages(project):
        info = _dist_info(site, name)
        if not info:
            continue
        meta = (
            Parser().parsestr((info / "METADATA").read_text(errors="replace", encoding="utf-8"))
            if (info / "METADATA").exists()
            else {}
        )
        top = (info / "top_level.txt").read_text(encoding="utf-8").split() if (info / "top_level.txt").exists() else []
        if not top and (info / "RECORD").exists():
            top = _record_modules(info)
        modules = [m for m in top if not m.startswith("_")] or top
        module = next((m for m in modules if _python_name(m) == _python_name(name)), modules[0] if modules else name)
        stub = site / f"{module}-stubs" / "__init__.pyi"
        package = site / module
        candidates = (
            stub,
            package / "__init__.pyi",
            package / "__init__.py",
            site / f"{module}.pyi",
            site / f"{module}.py",
        )
        entry = next((path for path in candidates if path.exists()), None)
        urls = [value.split(",", 1)[-1].strip() for value in meta.get_all("Project-URL") or []] if meta else []
        library = Library(
            name=meta.get("Name", name) if meta else name,
            ecosystem="python",
            version=meta.get("Version", info.name.rsplit("-", 1)[-1].removesuffix(".dist-info")) if meta else "?",
            path=package if package.exists() else (entry or site),
            summary=(meta.get("Summary") or "") if meta else "",
            homepage=(meta.get("Home-page") or (urls[0] if urls else "")) if meta else "",
            entry=entry,
        )
        body = meta.get_payload() if meta else ""
        if isinstance(body, str) and body.strip():
            library.readme_text = body
        library.declared, library.declared_in = _python_declared(project, library.name)
        if len(modules) > 1:
            library.notes.append(f"modules: {', '.join(modules)}")
        return library
    raise NotFound(name)


def _record_modules(info: Path) -> list[str]:
    """Top-level modules of a distribution from its RECORD, when top_level.txt is missing."""
    modules = set()
    for line in (info / "RECORD").read_text(encoding="utf-8").splitlines():
        first = line.split(",", 1)[0].split("/", 1)[0]
        if first and not first.startswith(("..", "__pycache__")) and not first.endswith((".dist-info", ".data")):
            modules.add(first.removesuffix(".py"))
    return sorted(modules)


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({ast.unparse(node.args)}){returns}"


def _class_line(node: ast.ClassDef) -> str:
    bases = ", ".join(ast.unparse(base) for base in node.bases)
    return f"class {node.name}({bases})" if bases else f"class {node.name}"


def python_api(entry: Path) -> list[str]:
    """Public top-level names of a module: signatures, classes with public methods, re-exports."""
    try:
        tree = ast.parse(entry.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    exported: list[str] | None = None
    lines: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            with contextlib.suppress(ValueError, SyntaxError, TypeError):
                exported = [str(v) for v in ast.literal_eval(node.value)]

    def public(name: str) -> bool:
        return name in exported if exported is not None else not name.startswith("_")

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and public(node.name):
            lines.append(_signature(node))
        elif isinstance(node, ast.ClassDef) and public(node.name):
            lines.append(_class_line(node))
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and (
                    not item.name.startswith("_") or item.name == "__init__"
                ):
                    lines.append("    " + _signature(item))
        elif isinstance(node, ast.ImportFrom):
            names = [alias.asname or alias.name for alias in node.names if public(alias.asname or alias.name)]
            if names and (node.level or exported is not None):
                source = "." * node.level + (node.module or "")
                lines.append(f"from {source} import {', '.join(names)}")
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and public(target.id) and target.id != "__all__":
                    annotation = f": {ast.unparse(node.annotation)}" if isinstance(node, ast.AnnAssign) else ""
                    lines.append(f"{target.id}{annotation}")
    return _group_imports(lines)


def _group_imports(lines: list[str]) -> list[str]:
    """``from x import a`` and ``from x import b`` become ``from x import a, b`` (first position kept)."""
    grouped: list[str] = []
    by_source: dict[str, int] = {}
    for line in lines:
        match = re.match(r"from (\S+) import (.+)", line)
        if not match:
            grouped.append(line)
        elif match.group(1) in by_source:
            grouped[by_source[match.group(1)]] += ", " + match.group(2)
        else:
            by_source[match.group(1)] = len(grouped)
            grouped.append(line)
    return grouped


def python_find(root: Path, symbol: str) -> list[Definition]:
    *outer, name = symbol.split(".")
    found: list[Definition] = []
    files = [root] if root.is_file() else list(_walk(root, (".py", ".pyi")))
    for file in files:
        try:
            tree = ast.parse(file.read_text(errors="replace", encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            if outer and isinstance(node, ast.ClassDef) and node.name == outer[-1]:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name == name:
                        found.append(Definition(file, item.lineno, _describe_python(item, f"{node.name}.")))
            elif not outer and node.name == name:
                found.append(Definition(file, node.lineno, _describe_python(node)))
    return found


def _describe_python(node, prefix: str = "") -> str:
    head = _class_line(node) if isinstance(node, ast.ClassDef) else _signature(node)
    if prefix:
        head = head.replace(f"def {node.name}", f"def {prefix}{node.name}", 1)
    doc = ast.get_docstring(node) or ""
    lines = [head]
    if doc:
        lines += ["    " + line for line in doc.strip().split("\n\n")[0].splitlines()[:FIND_CONTEXT]]
    if isinstance(node, ast.ClassDef):
        methods = [_signature(i) for i in node.body if isinstance(i, ast.FunctionDef | ast.AsyncFunctionDef)
                   and (not i.name.startswith("_") or i.name == "__init__")]  # fmt: skip
        lines += ["    " + method for method in methods[:FIND_CONTEXT]]
    return "\n".join(lines)


# --- Node -------------------------------------------------------------------------------------

DTS_EXPORT = re.compile(
    r"^\s*export\s+(?:declare\s+)?(?:default\s+)?(?:abstract\s+)?"
    r"(function|class|interface|type|const|let|var|enum|namespace)\s+([A-Za-z_$][\w$]*)"
)


def _package_dir(project: Path, name: str) -> Path | None:
    for directory in _ancestors(project):
        candidate = directory / "node_modules" / name
        if (candidate / "package.json").exists():
            return candidate
    return None


def _read_json(path: Path) -> dict | None:
    """A package.json, or None when it is unreadable (a broken install must not crash the report)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _types_entry(package: Path, data: dict) -> Path | None:
    candidates = [data.get("types"), data.get("typings")]
    exports = data.get("exports")
    if isinstance(exports, dict):
        root = exports.get(".", exports)
        if isinstance(root, dict):
            candidates.append(root.get("types"))
            for value in root.values():
                if isinstance(value, dict):
                    candidates.append(value.get("types"))
    candidates += ["index.d.ts", "dist/index.d.ts", "lib/index.d.ts", "types/index.d.ts"]
    for candidate in candidates:
        if isinstance(candidate, str) and (package / candidate).is_file():
            return package / candidate
    return None


def find_node(project: Path, name: str) -> Library:
    package = _package_dir(project, name)
    if not package:
        raise NotFound(name)
    data = _read_json(package / "package.json")
    unreadable = data is None
    data = data or {}
    library = Library(
        name=name,
        ecosystem="node",
        version=str(data.get("version", "?")),
        path=package,
        summary=str(data.get("description") or ""),
        homepage=str(data.get("homepage") or ""),
        readme=_readme_in(package),
        entry=_types_entry(package, data),
    )
    if unreadable:
        library.notes.append(f"{shorten_home(package / 'package.json')} is unreadable or not valid JSON")
    if library.entry is None:
        types_name = "@types/" + name.lstrip("@").replace("/", "__")
        types_dir = _package_dir(project, types_name)
        if types_dir:
            types_data = _read_json(types_dir / "package.json") or {}
            library.entry = _types_entry(types_dir, types_data)
            library.notes.append(f"types from {types_name} {types_data.get('version', '?')}")
        else:
            library.notes.append("no type declarations shipped (and no @types package installed)")
    manifest = _find_up(project, "package.json")
    if manifest:
        try:
            own = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            own = {}
        for group in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            spec = (own.get(group) or {}).get(name)
            if spec:
                library.declared, library.declared_in = f"{name}@{spec}", f"{manifest} ({group})"
                break
    return library


DTS_DECLARE = re.compile(r"^declare\s+(function|class|const|namespace|enum)\s+[A-Za-z_$]")


def dts_api(entry: Path) -> list[str]:
    """Exported declarations, multi-line ``export { … }`` lists joined, and the ``declare``s behind ``export =``."""
    lines: list[str] = []
    source = entry.read_text(encoding="utf-8", errors="replace").splitlines()
    index = 0
    while index < len(source):
        line = source[index]
        stripped = line.strip()
        if re.match(r"export\s+(type\s+)?\{", stripped) and "}" not in stripped:
            block = [stripped]
            while index + 1 < len(source) and "}" not in source[index]:
                index += 1
                block.append(source[index].strip())
            joined = " ".join(re.sub(r"//.*", "", part) for part in block)
            lines.append(re.sub(r"\s+", " ", joined).replace(" ,", ",").strip())
        elif (
            DTS_EXPORT.match(line)
            or DTS_DECLARE.match(line)
            or stripped.startswith(("export *", "export =", "export {"))
        ):
            entry_line = stripped.rstrip("{").rstrip()
            if entry_line not in lines:
                lines.append(entry_line)
        index += 1
    return lines


def text_find(root: Path, pattern: re.Pattern, suffixes: tuple[str, ...]) -> list[Definition]:
    found = []
    for file in [root] if root.is_file() else _walk(root, suffixes):
        try:
            lines = file.read_text(errors="replace", encoding="utf-8").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines):
            if pattern.search(line):
                start = index
                while start > 0 and lines[start - 1].strip().startswith(("*", "/**", "///", "//", "#[", "@")):
                    start -= 1
                block = lines[start : index + 1]
                opened = "{" in line
                depth = line.count("{") - line.count("}")
                follow = index + 1
                # Follow the body even when its brace opens a few lines later (multi-line generics).
                while follow < len(lines) and follow - index < FIND_CONTEXT and (depth > 0 or not opened):
                    if not opened and lines[follow - 1].rstrip().endswith(";"):
                        break
                    block.append(lines[follow])
                    opened = opened or "{" in lines[follow]
                    depth += lines[follow].count("{") - lines[follow].count("}")
                    follow += 1
                if follow - index >= FIND_CONTEXT and depth > 0:
                    block.append("  … (truncated)")
                found.append(Definition(file, index + 1, "\n".join(block)))
    return found


# --- Rust -------------------------------------------------------------------------------------


def cargo_home() -> Path:
    return Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo")


def find_rust(project: Path, name: str) -> Library:
    lock = _find_up(project, "Cargo.lock")
    if not lock:
        raise NotFound(name)
    versions = re.findall(
        rf'\[\[package\]\]\nname = "{re.escape(name)}"\nversion = "([^"]+)"', lock.read_text(encoding="utf-8")
    )
    if not versions:
        raise NotFound(name)
    version = versions[-1]
    sources = sorted((cargo_home() / "registry" / "src").glob(f"*/{name}-{version}"))
    path = sources[0] if sources else None
    library = Library(name=name, ecosystem="rust", version=version, path=path or lock)
    if len(versions) > 1:
        library.notes.append(f"several versions in Cargo.lock: {', '.join(versions)}")
    if path:
        library.readme = _readme_in(path)
        library.entry = path / "src" / "lib.rs" if (path / "src" / "lib.rs").exists() else None
        try:
            package = tomllib.loads((path / "Cargo.toml").read_text(encoding="utf-8")).get("package", {})
            library.summary = str(package.get("description") or "")
            library.homepage = str(package.get("documentation") or package.get("repository") or "")
        except (OSError, tomllib.TOMLDecodeError):
            pass
    else:
        library.notes.append("source not in the Cargo registry cache (run `cargo fetch`)")
    manifest = _find_up(project, "Cargo.toml")
    if manifest:
        match = re.search(rf"^\s*{re.escape(name)}\s*=\s*(.+)$", manifest.read_text(encoding="utf-8"), re.MULTILINE)
        if match:
            library.declared, library.declared_in = f"{name} = {match.group(1).strip()}", str(manifest)
    return library


RUST_PUB = re.compile(r"^pub\s+(?:async\s+|const\s+|unsafe\s+)*(fn|struct|enum|trait|type|const|static|mod|use)\b")


def rust_api(entry: Path) -> list[str]:
    text = entry.read_text(encoding="utf-8", errors="replace")
    return [line.strip().rstrip("{").rstrip() for line in text.splitlines() if RUST_PUB.match(line)]


# --- Go -----------------------------------------------------------------------------------------


def gomodcache() -> Path:
    if os.environ.get("GOMODCACHE"):
        return Path(os.environ["GOMODCACHE"])
    gopath = os.environ.get("GOPATH") or str(Path.home() / "go")
    return Path(gopath.split(os.pathsep)[0]) / "pkg" / "mod"


def _escape_module(path: str) -> str:
    return re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), path)


def find_go(project: Path, name: str) -> Library:
    gomod = _find_up(project, "go.mod")
    if not gomod:
        raise NotFound(name)
    match = re.search(
        rf"^\s*(?:require\s+)?{re.escape(name)}\s+(v\S+)", gomod.read_text(encoding="utf-8"), re.MULTILINE
    )
    if not match:
        raise NotFound(name)
    version = match.group(1)
    path = gomodcache() / f"{_escape_module(name)}@{version}"
    library = Library(name=name, ecosystem="go", version=version, path=path if path.is_dir() else gomod)
    library.declared, library.declared_in = f"{name} {version}", str(gomod)
    if path.is_dir():
        library.readme = _readme_in(path)
        library.entry = path
    else:
        library.notes.append("source not in the module cache (run `go mod download`)")
    return library


GO_EXPORTED = re.compile(r"^(func\s+(\([^)]*\)\s*)?[A-Z]\w*|type\s+[A-Z]\w*|var\s+[A-Z]\w*|const\s+[A-Z]\w*)")


def go_api(directory: Path) -> list[str]:
    lines = []
    for file in sorted(directory.glob("*.go")):
        if file.name.endswith("_test.go"):
            continue
        lines += [line.rstrip("{").rstrip() for line in file.read_text(errors="replace", encoding="utf-8").splitlines()
                  if GO_EXPORTED.match(line)]  # fmt: skip
    return lines


# --- Dispatch -------------------------------------------------------------------------------------

FINDERS = {"python": find_python, "node": find_node, "rust": find_rust, "go": find_go}


def locate(project: Path, name: str, ecosystem: str | None = None) -> Library:
    order = [ecosystem] if ecosystem else list(FINDERS)
    for eco in order:
        try:
            return FINDERS[eco](project, name)
        except NotFound:
            continue
    raise NotFound(name)


def api(library: Library) -> list[str]:
    if not library.entry:
        return []
    if library.ecosystem == "python":
        return python_api(library.entry)
    if library.ecosystem == "node":
        return dts_api(library.entry)
    if library.ecosystem == "rust":
        return rust_api(library.entry)
    return go_api(library.entry)


def find_symbol(library: Library, symbol: str) -> list[Definition]:
    name = re.escape(symbol.split(".")[-1])
    if library.ecosystem == "python":
        return python_find(library.path, symbol)
    if library.ecosystem == "node":
        root = (
            library.entry.parent if library.entry and not library.entry.is_relative_to(library.path) else library.path
        )
        pattern = re.compile(rf"\b(function|class|interface|type|const|let|var|enum|namespace)\s+{name}\b")
        return text_find(root, pattern, (".d.ts", ".d.mts", ".d.cts"))
    if library.ecosystem == "rust":
        return text_find(library.path, re.compile(rf"\b(fn|struct|enum|trait|type|const|static)\s+{name}\b"), (".rs",))
    return text_find(library.path, re.compile(rf"^(func\s+(\([^)]*\)\s*)?|type\s+|var\s+|const\s+){name}\b"), (".go",))


def readme_text(library: Library) -> str:
    if library.readme:
        return library.readme.read_text(errors="replace", encoding="utf-8")
    return library.readme_text


# --- Output ---------------------------------------------------------------------------------------


def render(library: Library, *, mode: str, symbol: str | None = None, full_api: bool = False) -> str:
    st = Style.detect()
    lines = [f"libdocs: {library.name} {library.version} ({library.ecosystem}) · {shorten_home(library.path)}"]
    if st.enabled:
        lines = [st.header("ctk libdocs", f"{library.name} {library.version} ({library.ecosystem})"),
                 f"  {st.muted('path')} {st.accent2(shorten_home(library.path))}"]  # fmt: skip
    indent = "  "
    if library.declared:
        lines.append(f"{indent}declared: {library.declared} in {shorten_home(library.declared_in)}")
    if library.summary:
        lines.append(f"{indent}summary: {library.summary}")
    if library.homepage:
        lines.append(f"{indent}docs: {library.homepage}")
    lines += [f"{indent}note: {note}" for note in library.notes]
    if mode == "readme":
        text = readme_text(library)
        return "\n".join([*lines, "", text or "(no README)"])
    if mode == "find" and symbol:
        found = find_symbol(library, symbol)
        if not found:
            return "\n".join([*lines, f"{indent}{symbol}: not found in the installed sources"])
        out = [*lines]
        for definition in found[:10]:
            out += ["", f"{shorten_home(definition.file)}:{definition.line}", definition.text]
        if len(found) > 10:
            out.append(f"… {len(found) - 10} more definitions")
        return "\n".join(out)
    readme = readme_text(library)
    if library.readme or readme:
        where = shorten_home(library.readme) if library.readme else "package metadata"
        lines.append(f"{indent}readme: {where} ({len(readme.splitlines())} lines; --readme to print)")
        headings = [line.strip() for line in readme.splitlines() if line.startswith("#")][:README_PREVIEW]
        if headings:
            lines.append(f"{indent}sections: " + " · ".join(h.lstrip("#").strip() for h in headings))
    names = api(library)
    if library.entry:
        lines.append(f"{indent}api ({shorten_home(library.entry)}):")
        shown = names if full_api else names[:API_LINES]
        lines += [f"{indent}  {line}" for line in shown] or [f"{indent}  (no public names found)"]
        if len(names) > len(shown):
            lines.append(f"{indent}  … {len(names) - len(shown)} more (--api for all, --find NAME for one)")
    return "\n".join(lines)


def run(args) -> int:
    project = Path(args.path).expanduser().resolve()
    try:
        library = locate(project, args.package, args.ecosystem)
    except NotFound:
        looked = ", ".join([args.ecosystem] if args.ecosystem else FINDERS)
        print(f"libdocs: {args.package} is not installed for {project} (looked in: {looked})", file=sys.stderr)
        return 1
    if args.json:
        data = asdict(library)
        data["api"] = api(library)
        if args.find:
            data["definitions"] = [asdict(d) for d in find_symbol(library, args.find)]
        print(json.dumps(data, indent=2, default=str))
        return 0
    mode = "readme" if args.readme else "find" if args.find else "summary"
    print(render(library, mode=mode, symbol=args.find, full_api=args.api))
    return 0
