"""``format-file`` (PostToolUse on Edit/Write): format only the edited file.

A formatter runs only when the project configures it (a config file, or the
language's canonical formatter such as gofmt), and only from the project's own
installation when one exists. Silent on success and when nothing applies; a
failing formatter is reported to Claude in a few lines.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .base import Event, Outcome, is_within, project_root

TIMEOUT = 20
SKIP_DIRS = {"node_modules", ".venv", "venv", ".git", "vendor", "target", "dist", "build", "__pycache__"}
PRETTIER_SUFFIXES = {
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".json", ".jsonc",
    ".css", ".scss", ".less", ".html", ".vue", ".svelte", ".md", ".mdx", ".yaml", ".yml", ".graphql",
}  # fmt: skip
BIOME_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".json", ".jsonc", ".css"}


def _ancestors(start: Path, root: Path) -> list[Path]:
    """``start`` and its parents up to and including ``root``."""
    chain = [start]
    for parent in start.parents:
        if not is_within(parent, root):
            break
        chain.append(parent)
    return chain


def _find_up(start: Path, root: Path, names: tuple[str, ...]) -> Path | None:
    for directory in _ancestors(start, root):
        for name in names:
            if (directory / name).exists():
                return directory / name
    return None


def _pyproject_has(start: Path, root: Path, table: str) -> bool:
    for directory in _ancestors(start, root):
        path = directory / "pyproject.toml"
        if path.is_file():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                return False
            return table in data.get("tool", {})
    return False


def _local_bin(start: Path, root: Path, name: str, *, venv: bool = False) -> str | None:
    """The project's own copy of a tool (``node_modules/.bin`` or ``.venv/bin``)."""
    sub = (".venv", "bin") if venv else ("node_modules", ".bin")
    for directory in _ancestors(start, root):
        candidate = directory.joinpath(*sub, name)
        if candidate.is_file():
            return str(candidate)
    return None


def _python_tool(file: Path, root: Path, name: str) -> str | None:
    return _local_bin(file.parent, root, name, venv=True) or shutil.which(name)


def _ruff(file: Path, root: Path) -> list[str] | None:
    configured = _find_up(file.parent, root, ("ruff.toml", ".ruff.toml")) or _pyproject_has(file.parent, root, "ruff")
    tool = _python_tool(file, root, "ruff") if configured else None
    return [tool, "format", "--quiet", str(file)] if tool else None


def _black(file: Path, root: Path) -> list[str] | None:
    tool = _python_tool(file, root, "black") if _pyproject_has(file.parent, root, "black") else None
    return [tool, "--quiet", str(file)] if tool else None


def _package_json_has(start: Path, root: Path, key: str) -> bool:
    found = _find_up(start, root, ("package.json",))
    if not found:
        return False
    try:
        return key in json.loads(found.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False


PRETTIER_CONFIGS = (
    ".prettierrc", ".prettierrc.json", ".prettierrc.yaml", ".prettierrc.yml", ".prettierrc.json5",
    ".prettierrc.js", ".prettierrc.cjs", ".prettierrc.mjs", ".prettierrc.toml",
    "prettier.config.js", "prettier.config.cjs", "prettier.config.mjs", "prettier.config.ts",
)  # fmt: skip


def _prettier(file: Path, root: Path) -> list[str] | None:
    if file.suffix not in PRETTIER_SUFFIXES:
        return None
    configured = _find_up(file.parent, root, PRETTIER_CONFIGS) or _package_json_has(file.parent, root, "prettier")
    tool = _local_bin(file.parent, root, "prettier") if configured else None
    return [tool, "--write", "--log-level", "warn", str(file)] if tool else None


def _biome(file: Path, root: Path) -> list[str] | None:
    if file.suffix not in BIOME_SUFFIXES or not _find_up(file.parent, root, ("biome.json", "biome.jsonc")):
        return None
    tool = _local_bin(file.parent, root, "biome")
    return [tool, "format", "--write", str(file)] if tool else None


def _rust_edition(manifest: Path) -> str:
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return "2021"
    edition = data.get("package", {}).get("edition") or data.get("workspace", {}).get("package", {}).get("edition")
    return str(edition) if isinstance(edition, str | int) else "2021"


def _rustfmt(file: Path, root: Path) -> list[str] | None:
    manifest = _find_up(file.parent, root, ("Cargo.toml",))
    tool = shutil.which("rustfmt") if manifest else None
    return [tool, "--edition", _rust_edition(manifest), str(file)] if tool and manifest else None


def _gofmt(file: Path, root: Path) -> list[str] | None:
    tool = shutil.which("gofmt") if _find_up(file.parent, root, ("go.mod",)) else None
    return [tool, "-w", str(file)] if tool else None


def _stylua(file: Path, root: Path) -> list[str] | None:
    tool = shutil.which("stylua") if _find_up(file.parent, root, ("stylua.toml", ".stylua.toml")) else None
    return [tool, str(file)] if tool else None


def _clang_format(file: Path, root: Path) -> list[str] | None:
    tool = shutil.which("clang-format") if _find_up(file.parent, root, (".clang-format", "_clang-format")) else None
    return [tool, "-i", str(file)] if tool else None


@dataclass(frozen=True)
class Formatter:
    name: str
    suffixes: frozenset[str]
    command: Callable[[Path, Path], list[str] | None]


C_SUFFIXES = {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".m", ".mm"}

# First match wins: a project that configures several formatters for one language gets the first.
FORMATTERS = (
    Formatter("ruff", frozenset({".py", ".pyi"}), _ruff),
    Formatter("black", frozenset({".py", ".pyi"}), _black),
    Formatter("biome", frozenset(BIOME_SUFFIXES), _biome),
    Formatter("prettier", frozenset(PRETTIER_SUFFIXES), _prettier),
    Formatter("rustfmt", frozenset({".rs"}), _rustfmt),
    Formatter("gofmt", frozenset({".go"}), _gofmt),
    Formatter("stylua", frozenset({".lua"}), _stylua),
    Formatter("clang-format", frozenset(C_SUFFIXES), _clang_format),
)


def formatter_for(file: Path, root: Path) -> tuple[str, list[str]] | None:
    for formatter in FORMATTERS:
        if file.suffix in formatter.suffixes:
            command = formatter.command(file, root)
            if command:
                return formatter.name, command
    return None


def handle(event: Event) -> Outcome:
    raw = event.tool_input.get("file_path")
    if not raw:
        return Outcome()
    file = Path(str(raw))
    file = file if file.is_absolute() else event.cwd / file
    root = project_root(event.cwd)
    if not file.is_file() or not is_within(file, root):
        return Outcome()
    if any(part in SKIP_DIRS for part in file.relative_to(root).parts[:-1]):
        return Outcome()
    found = formatter_for(file, root)
    if not found:
        return Outcome()
    name, command = found
    try:
        done = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return Outcome()
    if done.returncode == 0:
        return Outcome()
    detail = "\n".join((done.stderr or done.stdout).strip().splitlines()[:8])
    return Outcome.context("PostToolUse", f"format-file: {name} could not format {file.name}:\n{detail}")
