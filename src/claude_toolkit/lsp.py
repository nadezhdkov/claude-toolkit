"""``ctk lsp``: language servers for the current project.

Claude Code gets code intelligence from LSP plugins in the official
marketplace; each plugin needs its language server binary on PATH. This
command detects the project's languages and reports, and optionally
installs (with confirmation), the missing binary and plugin.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .common import Host, confirm, detect_host, which
from .style import Style, shorten_home

MARKETPLACE = "claude-plugins-official"
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "target", "__pycache__", ".godot", "vendor"}
MIN_FILES = 3


@dataclass(frozen=True)
class LanguageServer:
    language: str
    plugin: str
    binary: str
    extensions: tuple[str, ...]
    install: dict[str, str]  # package manager or "npm"/"go"/"any" -> command

    def install_command(self, host: Host) -> str | None:
        if host.package_manager and host.package_manager in self.install:
            return self.install[host.package_manager]
        for tool in ("npm", "go", "dotnet", "gem", "any"):
            if tool in self.install and (tool == "any" or which(tool)):
                return self.install[tool]
        return None


SERVERS = (
    LanguageServer(
        "Python",
        "pyright-lsp",
        "pyright-langserver",
        (".py", ".pyi"),
        {"npm": "npm install -g pyright", "any": "uv tool install pyright"},
    ),
    LanguageServer(
        "TypeScript/JavaScript",
        "typescript-lsp",
        "typescript-language-server",
        (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs"),
        {"npm": "npm install -g typescript-language-server typescript"},
    ),
    LanguageServer("Go", "gopls-lsp", "gopls", (".go",), {"go": "go install golang.org/x/tools/gopls@latest"}),
    LanguageServer(
        "Rust",
        "rust-analyzer-lsp",
        "rust-analyzer",
        (".rs",),
        {
            "pacman": "sudo pacman -S --needed rust-analyzer",
            "brew": "brew install rust-analyzer",
            "any": "rustup component add rust-analyzer",
        },
    ),
    LanguageServer(
        "C/C++",
        "clangd-lsp",
        "clangd",
        (".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hxx"),
        {
            "pacman": "sudo pacman -S --needed clang",
            "apt": "sudo apt install clangd",
            "dnf": "sudo dnf install clang-tools-extra",
            "brew": "brew install llvm",
        },
    ),
    LanguageServer(
        "Java",
        "jdtls-lsp",
        "jdtls",
        (".java",),
        {"pacman": "yay -S jdtls  # AUR", "brew": "brew install jdtls"},
    ),
    LanguageServer(
        "Kotlin", "kotlin-lsp", "kotlin-lsp", (".kt", ".kts"), {"brew": "brew install JetBrains/utils/kotlin-lsp"}
    ),
    LanguageServer("C#", "csharp-lsp", "csharp-ls", (".cs",), {"dotnet": "dotnet tool install --global csharp-ls"}),
    LanguageServer(
        "Lua",
        "lua-lsp",
        "lua-language-server",
        (".lua",),
        {"pacman": "sudo pacman -S --needed lua-language-server", "brew": "brew install lua-language-server"},
    ),
    LanguageServer("PHP", "php-lsp", "intelephense", (".php",), {"npm": "npm install -g intelephense"}),
    LanguageServer("Ruby", "ruby-lsp", "ruby-lsp", (".rb", ".rake"), {"gem": "gem install ruby-lsp"}),
    LanguageServer("Swift", "swift-lsp", "sourcekit-lsp", (".swift",), {"any": "install the Swift toolchain"}),
)
BY_EXTENSION = {ext: server for server in SERVERS for ext in server.extensions}


def project_files(root: Path, limit: int = 50_000) -> list[str]:
    """Tracked files via git when possible, else a bounded directory walk."""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if done.returncode == 0 and done.stdout:
            return [p for p in done.stdout.decode(errors="replace").split("\0") if p][:limit]
    except (OSError, subprocess.TimeoutExpired):
        pass
    found: list[str] = []
    stack = [root]
    while stack and len(found) < limit:
        directory = stack.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir() and entry.name not in SKIP_DIRS and not entry.is_symlink():
                stack.append(entry)
            elif entry.is_file():
                found.append(entry.relative_to(root).as_posix())
    return found


def detect_languages(root: Path) -> list[tuple[LanguageServer, int]]:
    counts: Counter = Counter()
    for name in project_files(root):
        server = BY_EXTENSION.get(Path(name).suffix.lower())
        if server:
            counts[server.plugin] += 1
    by_plugin = {server.plugin: server for server in SERVERS}
    return [(by_plugin[plugin], n) for plugin, n in counts.most_common() if n >= MIN_FILES]


def installed_plugins(claude_home: Path | None = None) -> set[str]:
    """Plugin names (without marketplace) that are installed and not disabled."""
    home = claude_home or Path.home() / ".claude"
    names: set[str] = set()
    try:
        data = json.loads((home / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
        names.update(key.split("@")[0] for key in data.get("plugins", {}))
    except (OSError, json.JSONDecodeError):
        pass
    try:
        enabled = json.loads((home / "settings.json").read_text(encoding="utf-8")).get("enabledPlugins", {})
        for key, on in enabled.items():
            name = key.split("@")[0]
            if on:
                names.add(name)
            else:
                names.discard(name)
    except (OSError, json.JSONDecodeError):
        pass
    return names


@dataclass
class Status:
    server: LanguageServer
    files: int
    binary: bool
    plugin: bool

    @property
    def ready(self) -> bool:
        return self.binary and self.plugin


def status(root: Path, claude_home: Path | None = None) -> list[Status]:
    plugins = installed_plugins(claude_home)
    return [
        Status(server, n, which(server.binary) is not None, server.plugin in plugins)
        for server, n in detect_languages(root)
    ]


def render(root: Path, statuses: list[Status], host: Host, style: Style | None = None) -> str:
    st = style or Style.detect()
    if st.enabled:
        return _render_styled(root, statuses, host, st)
    lines = [f"ctk lsp · {root}"]
    if not statuses:
        lines.append("no languages with an official LSP plugin detected")
        return "\n".join(lines)
    for status in statuses:
        mark = "✓" if status.ready else "✗"
        parts = [f"{mark} {status.server.language} ({status.files} files)"]
        parts.append(f"server {status.server.binary}: {'ok' if status.binary else 'missing'}")
        parts.append(f"plugin {status.server.plugin}: {'ok' if status.plugin else 'missing'}")
        lines.append(" · ".join(parts))
        if not status.binary:
            lines.append(f"    install server: {status.server.install_command(host) or 'see the language docs'}")
        if not status.plugin:
            lines.append(f"    install plugin: claude plugin install {status.server.plugin}@{MARKETPLACE}")
    if any(not status.ready for status in statuses):
        lines.append("run `ctk lsp --install` to install the missing pieces (asks before each change)")
    return "\n".join(lines)


def _render_styled(root: Path, statuses: list[Status], host: Host, st: Style) -> str:
    lines = [st.header("ctk lsp", shorten_home(root)), ""]
    if not statuses:
        lines.append(f"  {st.muted('no languages with an official LSP plugin detected')}")
        return "\n".join(lines)

    def piece(ok: bool, name: str, width: int) -> str:
        padded = name.ljust(width)
        return f"{st.ok('✓') if ok else st.err('✗')} {padded if ok else st.err(padded)}"

    lang_w = max(len(status.server.language) for status in statuses)
    bin_w = max(len(status.server.binary) for status in statuses)
    heading = f"    {'language'.ljust(lang_w)}  {'files':>11}   {'  server'.ljust(bin_w + 2)}     plugin"
    lines.append(st.muted(heading))
    for status in statuses:
        mark = st.ok("✓", bold=True) if status.ready else st.err("✗", bold=True)
        files = st.muted(f"{status.files:>5} files")
        row = f"  {mark} {st.bold(status.server.language.ljust(lang_w))}  {files}   "
        row += piece(status.binary, status.server.binary, bin_w) + "   " + piece(status.plugin, status.server.plugin, 0)
        lines.append(row.rstrip())
        if not status.binary:
            hint = status.server.install_command(host)
            lines.append(f"      {st.command(hint) if hint else st.muted('see the language documentation')}")
        if not status.plugin:
            lines.append(f"      {st.command(f'claude plugin install {status.server.plugin}@{MARKETPLACE}')}")
    ready = sum(status.ready for status in statuses)
    missing = len(statuses) - ready
    lines.append("")
    summary = [st.ok(f"{ready} ready", bold=True)] if ready else []
    if missing:
        summary.append(st.warn(f"{missing} need{'s' if missing == 1 else ''} setup", bold=True))
    tail = (
        f"   {st.accent('→')} {st.bold('ctk lsp --install')} {st.muted('(asks before each change)')}" if missing else ""
    )
    lines.append("  " + st.muted(" · ").join(summary) + tail)
    return "\n".join(lines)


def install(statuses: list[Status], host: Host, *, assume_yes: bool) -> list[str]:
    """Install missing servers and plugins, asking before each one. Returns what was done."""
    done: list[str] = []
    for st in statuses:
        if not st.binary:
            command = st.server.install_command(host)
            if (
                command
                and not command.startswith(("install ", "yay "))
                and confirm(f"Run `{command}`?", assume_yes=assume_yes)
            ):
                result = subprocess.run(command, shell=True, check=False)
                done.append(f"{command} -> exit {result.returncode}")
        if not st.plugin and which("claude"):
            command = ["claude", "plugin", "install", f"{st.server.plugin}@{MARKETPLACE}"]
            if confirm(f"Run `{' '.join(command)}`?", assume_yes=assume_yes):
                result = subprocess.run(command, check=False)
                done.append(f"{' '.join(command)} -> exit {result.returncode}")
    return done


def default_host() -> Host:
    return detect_host()
