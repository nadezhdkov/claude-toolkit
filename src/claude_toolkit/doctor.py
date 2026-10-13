"""``ctk doctor``: compare a project's pinned toolchain with what is installed."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import pep440, semver
from .common import Host, detect_host, parse_version, run_text, which
from .style import Style, shorten_home


@dataclass
class Finding:
    level: str  # "error" | "warn" | "ok"
    check: str
    message: str
    fix: str | None = None


@dataclass
class Report:
    path: str
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, check: str, message: str, fix: str | None = None) -> None:
        self.findings.append(Finding(level, check, message, fix))

    @property
    def errors(self) -> int:
        return sum(f.level == "error" for f in self.findings)

    @property
    def warnings(self) -> int:
        return sum(f.level == "warn" for f in self.findings)


_VERSION_COMMANDS = {
    "node": ["node", "--version"],
    "npm": ["npm", "--version"],
    "pnpm": ["pnpm", "--version"],
    "yarn": ["yarn", "--version"],
    "bun": ["bun", "--version"],
    "python": ["python3", "--version"],
    "go": ["go", "version"],
    "rust": ["rustc", "--version"],
    "ruby": ["ruby", "--version"],
    "java": ["java", "-version"],
}
_TOOL_VERSIONS_ALIASES = {"nodejs": "node", "golang": "go", "python": "python", "rust": "rust", "ruby": "ruby"}


def installed_version(tool: str) -> tuple[int, int, int] | None:
    command = _VERSION_COMMANDS.get(tool)
    if not command or not which(command[0]):
        return None
    output = run_text(command)
    if tool == "go" and output:
        output = output.replace("go version go", "")
    return parse_version(output)


def _fmt(version: tuple[int, ...] | None) -> str:
    return ".".join(map(str, version)) if version else "not installed"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


# --- Node -------------------------------------------------------------------


def _node_install_hint(spec: str) -> str:
    return f"install and select Node {spec} (nvm install {spec} && nvm use, fnm use {spec}, or mise use node@{spec})"


def check_node(root: Path, report: Report) -> None:
    package = root / "package.json"
    pins: list[tuple[str, str]] = []
    for name in (".nvmrc", ".node-version"):
        text = _read(root / name)
        if text and text.strip():
            pins.append((name, text.strip().splitlines()[0].strip().lstrip("v")))
    manifest: dict = {}
    if package.exists():
        try:
            manifest = json.loads(package.read_text())
        except (OSError, json.JSONDecodeError) as error:
            report.add("error", "package.json", f"package.json is not valid JSON: {error}")
    engines = manifest.get("engines", {}) if isinstance(manifest.get("engines"), dict) else {}
    if engines.get("node"):
        pins.append(("package.json engines.node", str(engines["node"])))
    if not pins and not package.exists():
        return
    node = installed_version("node")
    for source, spec in pins:
        if spec.startswith("lts/") or spec in ("lts", "node", "stable"):
            report.add("ok", "node", f"{source} asks for {spec}; alias not checked")
            continue
        if node is None:
            report.add(
                "error", "node", f"Node is required by {source} ({spec}) but not installed", _node_install_hint(spec)
            )
            continue
        try:
            ok = semver.satisfies(node, spec)
        except semver.UnsupportedRange:
            report.add("warn", "node", f"cannot evaluate {source} range {spec!r}; installed {_fmt(node)}")
            continue
        if ok:
            report.add("ok", "node", f"node {_fmt(node)} satisfies {source} ({spec})")
        else:
            pinned = parse_version(spec)
            same_major = pinned is not None and pinned[0] == node[0]
            level = "warn" if same_major and source != "package.json engines.node" else "error"
            report.add(level, "node", f"node {_fmt(node)} does not satisfy {source} ({spec})", _node_install_hint(spec))
    manager = manifest.get("packageManager")
    if isinstance(manager, str) and "@" in manager:
        name, _, wanted = manager.partition("@")
        wanted = wanted.split("+")[0]
        have = installed_version(name)
        if have is None:
            report.add("error", name, f"packageManager wants {manager} but {name} is not installed", "corepack enable")
        elif _fmt(have) != wanted:
            report.add("warn", name, f"{name} {_fmt(have)} differs from packageManager {wanted}", "corepack enable")
        else:
            report.add("ok", name, f"{name} {_fmt(have)} matches packageManager")
    _check_node_modules(root, report)


_LOCKS = (
    ("package-lock.json", "node_modules/.package-lock.json", "npm ci"),
    ("npm-shrinkwrap.json", "node_modules/.package-lock.json", "npm ci"),
    ("pnpm-lock.yaml", "node_modules/.modules.yaml", "pnpm install --frozen-lockfile"),
    ("yarn.lock", "node_modules/.yarn-state.yml", "yarn install --immutable"),
    ("bun.lock", "node_modules", "bun install --frozen-lockfile"),
    ("bun.lockb", "node_modules", "bun install --frozen-lockfile"),
)


def _check_node_modules(root: Path, report: Report) -> None:
    for lock, marker, fix in _LOCKS:
        lock_path = root / lock
        if not lock_path.exists():
            continue
        modules = root / "node_modules"
        marker_path = root / marker
        if not modules.exists():
            report.add("error", "node_modules", f"{lock} exists but node_modules is missing", fix)
        elif not marker_path.exists():
            if lock == "yarn.lock" and (modules / ".yarn-integrity").exists():
                marker_path = modules / ".yarn-integrity"
            else:
                report.add("warn", "node_modules", f"cannot tell whether node_modules matches {lock}", fix)
                return
        if marker_path.exists() and lock_path.stat().st_mtime > marker_path.stat().st_mtime + 1:
            report.add("warn", "node_modules", f"{lock} is newer than the installed node_modules", fix)
        elif modules.exists():
            report.add("ok", "node_modules", f"node_modules installed from {lock}")
        return


# --- Python -----------------------------------------------------------------


def _python_for(root: Path) -> tuple[str, tuple[int, int, int] | None]:
    venv = root / ".venv" / "bin" / "python"
    if venv.exists():
        return ".venv python", parse_version(run_text([str(venv), "--version"]))
    return "python3", installed_version("python")


def check_python(root: Path, report: Report) -> None:
    pyproject = root / "pyproject.toml"
    pins: list[tuple[str, str]] = []
    pinned = _read(root / ".python-version")
    if pinned and pinned.strip():
        pins.append((".python-version", pinned.strip().splitlines()[0].strip()))
    data: dict = {}
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
        except (OSError, tomllib.TOMLDecodeError) as error:
            report.add("error", "pyproject.toml", f"pyproject.toml is not valid TOML: {error}")
    requires = (data.get("project") or {}).get("requires-python")
    if requires:
        pins.append(("requires-python", str(requires)))
    if not pins and not (root / "uv.lock").exists():
        return
    label, python = _python_for(root)
    for source, spec in pins:
        if python is None:
            report.add("error", "python", f"Python is required by {source} ({spec}) but not found", "uv python install")
            continue
        clause = spec if source == "requires-python" else f"=={spec}.*" if spec.count(".") < 2 else f"=={spec}"
        try:
            ok = pep440.satisfies(python, clause)
        except pep440.UnsupportedSpecifier:
            report.add("warn", "python", f"cannot evaluate {source} {spec!r}; {label} is {_fmt(python)}")
            continue
        if ok:
            report.add("ok", "python", f"{label} {_fmt(python)} satisfies {source} ({spec})")
        else:
            report.add("error", "python", f"{label} {_fmt(python)} does not satisfy {source} ({spec})", "uv sync")
    lock = root / "uv.lock"
    if lock.exists():
        venv = root / ".venv"
        if not venv.exists():
            report.add("error", "uv", "uv.lock exists but .venv is missing", "uv sync")
        elif which("uv"):
            # uv knows exactly whether .venv matches the lock; directory mtimes do not.
            output = run_text(["uv", "sync", "--dry-run", "--offline", "--directory", str(root)], timeout=20) or ""
            if "Would make no changes" in output:
                report.add("ok", "uv", ".venv matches uv.lock")
            elif "Would " in output:
                report.add("warn", "uv", ".venv does not match uv.lock", "uv sync")
            else:
                report.add("warn", "uv", "could not verify .venv against uv.lock (uv sync --dry-run failed)")
        else:
            report.add("warn", "uv", "uv.lock exists but uv is not installed", "install uv")


# --- Go, Rust and .tool-versions -------------------------------------------


def check_go(root: Path, report: Report) -> None:
    text = _read(root / "go.mod")
    if not text:
        return
    match = re.search(r"^go\s+(\d+(?:\.\d+){0,2})", text, re.M)
    if not match:
        return
    wanted = parse_version(match.group(1))
    have = installed_version("go")
    if have is None:
        report.add("error", "go", f"go.mod requires Go {match.group(1)} but Go is not installed", "install Go")
    elif have < wanted:
        report.add("error", "go", f"Go {_fmt(have)} is older than go.mod requires ({match.group(1)})", "update Go")
    else:
        report.add("ok", "go", f"Go {_fmt(have)} satisfies go.mod ({match.group(1)})")


def check_rust(root: Path, report: Report) -> None:
    channel = None
    toml_file = root / "rust-toolchain.toml"
    if toml_file.exists():
        try:
            channel = tomllib.loads(toml_file.read_text()).get("toolchain", {}).get("channel")
        except (OSError, tomllib.TOMLDecodeError):
            report.add("warn", "rust", "rust-toolchain.toml is not valid TOML")
    elif (root / "rust-toolchain").exists():
        channel = (_read(root / "rust-toolchain") or "").strip() or None
    if not channel:
        return
    if which("rustup"):
        report.add("ok", "rust", f"rustup selects the pinned toolchain ({channel}) automatically")
        return
    have = installed_version("rust")
    wanted = parse_version(channel)
    if have is None:
        report.add("error", "rust", f"rust toolchain {channel} is pinned but rustc is not installed", "install rustup")
    elif wanted and have[: len(channel.split("."))] != wanted[: len(channel.split("."))]:
        report.add(
            "warn", "rust", f"rustc {_fmt(have)} differs from pinned {channel} and rustup is absent", "install rustup"
        )


def check_tool_versions(root: Path, report: Report) -> None:
    text = _read(root / ".tool-versions")
    if not text:
        return
    for line in text.splitlines():
        parts = line.split("#")[0].split()
        if len(parts) < 2:
            continue
        tool = _TOOL_VERSIONS_ALIASES.get(parts[0])
        wanted = parts[1]
        if tool is None or not re.match(r"^\d", wanted):
            continue
        have = installed_version(tool)
        width = wanted.count(".") + 1
        if have is None:
            report.add(
                "error", tool, f".tool-versions pins {parts[0]} {wanted} but it is not installed", "mise install"
            )
        elif _fmt(have).split(".")[:width] != wanted.split(".")[:width]:
            report.add("warn", tool, f"{tool} {_fmt(have)} differs from .tool-versions ({wanted})", "mise install")


PROJECT_CHECKS = (check_node, check_python, check_go, check_rust, check_tool_versions)


def check_project(root: Path) -> Report:
    report = Report(str(root))
    for check in PROJECT_CHECKS:
        check(root, report)
    return report


# --- Toolkit dependencies ---------------------------------------------------


@dataclass(frozen=True)
class Dependency:
    command: str
    purpose: str
    required: bool
    packages: dict[str, str]  # package manager -> install command
    # False until the command or hook that needs it ships; unreleased needs stay silent.
    shipped: bool = True

    def hint(self, host: Host) -> str | None:
        return self.packages.get(host.package_manager or "") or self.packages.get("any")


def _pm(pacman: str, apt: str | None = None, dnf: str | None = None, brew: str | None = None) -> dict[str, str]:
    return {
        "pacman": f"sudo pacman -S --needed {pacman}",
        "apt": f"sudo apt install {apt or pacman}",
        "dnf": f"sudo dnf install {dnf or pacman}",
        "brew": f"brew install {brew or pacman}",
    }


TOOLKIT_DEPENDENCIES = (
    Dependency("git", "version control", True, _pm("git")),
    Dependency(
        "uv",
        "installs and runs the toolkit",
        True,
        {**_pm("uv"), "any": "curl -LsSf https://astral.sh/uv/install.sh | sh"},
    ),
    Dependency(
        "claude", "Claude Code CLI (plugins, LSP)", True, {"any": "see https://docs.claude.com/en/docs/claude-code"}
    ),
    Dependency("gh", "GitHub workflows (PRs, CI)", False, _pm("github-cli", "gh", "gh", "gh")),
    Dependency("ffmpeg", "audio checks (`ctk audiocheck`) and desktop captures", False, _pm("ffmpeg")),
    Dependency("bwrap", "sandbox for untrusted code (upcoming `ctk sandbox`)", False, _pm("bubblewrap"), shipped=False),
    Dependency(
        "Xvfb",
        "headless desktop and Godot screenshots (`ctk shoot`)",
        False,
        _pm("xorg-server-xvfb", "xvfb", "xorg-x11-server-Xvfb", "--cask xquartz"),
    ),
    Dependency("gitleaks", "secret scanning before commits (`secrets` hook)", False, _pm("gitleaks")),
)


def check_toolkit(host: Host | None = None) -> Report:
    host = host or detect_host()
    report = Report("toolkit")
    python = installed_version("python")
    if python is None or python < (3, 11, 0):
        report.add("error", "python3", f"Python >= 3.11 is required (found {_fmt(python)})", "uv python install 3.12")
    else:
        report.add("ok", "python3", f"python {_fmt(python)}")
    for dep in TOOLKIT_DEPENDENCIES:
        if not dep.shipped:
            continue
        if which(dep.command):
            report.add("ok", dep.command, dep.purpose)
        else:
            report.add("error" if dep.required else "warn", dep.command, f"missing: {dep.purpose}", dep.hint(host))
    return report


# --- Output -----------------------------------------------------------------

_SYMBOL = {"error": "✗", "warn": "!", "ok": "✓"}


def render(report: Report, verbose: bool = False, style: Style | None = None) -> str:
    st = style or Style.detect()
    lines = [st.header("ctk doctor", shorten_home(report.path))]
    if st.enabled:
        lines.append("")
    indent = "  " if st.enabled else ""
    shown = [f for f in report.findings if verbose or f.level != "ok"]
    for finding in shown:
        symbol = st.level(finding.level, _SYMBOL[finding.level], bold=True)
        message = finding.message if finding.level != "ok" or not st.enabled else st.muted(finding.message)
        lines.append(f"{indent}{symbol} {message}")
        if finding.fix:
            styled = f"{indent}    {st.accent('↳')} {st.muted(finding.fix)}"
            lines.append(styled if st.enabled else f"    fix: {finding.fix}")
    if st.enabled and shown:
        lines.append("")
    if report.errors == 0 and report.warnings == 0:
        checked = len(report.findings)
        detail = f"{checked} checks" if checked else "no toolchain pins found"
        styled = f"{indent}{st.ok('✓ all good', bold=True)} {st.muted('· ' + detail)}"
        lines.append(styled if st.enabled else f"ok ({detail})")
    elif st.enabled:
        parts = []
        if report.errors:
            parts.append(st.err(f"{report.errors} error{'s' if report.errors != 1 else ''}", bold=True))
        if report.warnings:
            parts.append(st.warn(f"{report.warnings} warning{'s' if report.warnings != 1 else ''}", bold=True))
        lines.append(indent + st.muted(" · ").join(parts))
    else:
        lines.append(f"{report.errors} error(s), {report.warnings} warning(s)")
    return "\n".join(lines)


def to_json(report: Report) -> str:
    return json.dumps({"path": report.path, "findings": [asdict(f) for f in report.findings]}, indent=2)
