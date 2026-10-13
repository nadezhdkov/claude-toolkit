"""``ctk setup``: wire the toolkit into Claude Code, always asking first.

Steps are planned, shown, then applied one by one after confirmation:
1. add a short section to ``~/.claude/CLAUDE.md`` between markers, with a backup;
2. register this repository as a plugin marketplace and install the ``ctk``
   plugin (the hooks) with the ``claude`` CLI;
3. offer to install missing toolkit dependencies.
``ctk setup --uninstall`` removes the section and the plugin again.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .common import confirm, detect_host
from .doctor import TOOLKIT_DEPENDENCIES
from .style import Style

PLUGIN = "ctk"
MARKETPLACE = "ctk"
GITHUB_REPO = "nadezhdkov/claude-toolkit"
START = "<!-- claude-toolkit:start -->"
END = "<!-- claude-toolkit:end -->"

SNIPPET = f"""{START}
## claude-toolkit

Prefer these commands (installed by claude-toolkit) over ad-hoc scripts:

- `ctk doctor [path]`: toolchain versions vs project pins and dependency sync; run it first when a build or test fails oddly, and before starting work in an unfamiliar repo.
- `ctk runq -- <command>`: run tests, builds and linters whose output may be long; prints failures, summary and the full-log path, and keeps the exit code.
- `ctk lsp [path]`: which language servers the project needs and whether they are installed; `--install` asks before installing.
- `ctk sessions [--since DAYS]`: usage metrics from Claude Code transcripts (counts only).

If a ctk plugin hook blocks a command (guard-destructive, secrets) or reports failing tests, do not work around it: fix the cause or ask the user.

Commands that change the system ask for confirmation; without a terminal they print the plan and exit 3, so show the plan to the user and rerun with `--yes` only after they approve.
{END}
"""


@dataclass
class Step:
    description: str
    apply: callable  # type: ignore[valid-type]


def claude_home() -> Path:
    return Path.home() / ".claude"


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    directory = claude_home() / "backups" / "claude-toolkit"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{path.name}.{time.strftime('%Y%m%d-%H%M%S')}"
    target.write_bytes(path.read_bytes())
    return target


def strip_snippet(text: str) -> str:
    """Remove a previously installed section (markers included)."""
    if START not in text or END not in text:
        return text
    before, _, rest = text.partition(START)
    _, _, after = rest.partition(END)
    joined = before.rstrip("\n") + ("\n\n" if before.strip() and after.strip() else "\n") + after.lstrip("\n")
    return joined if joined.strip() else ""


def with_snippet(text: str) -> str:
    """Idempotently insert or refresh the section at the end of CLAUDE.md."""
    base = strip_snippet(text).rstrip("\n")
    return (base + "\n\n" if base else "") + SNIPPET


def claude_cli() -> str | None:
    return shutil.which("claude")


def marketplace_source() -> str:
    """This checkout when ctk runs from one (editable install), otherwise the GitHub repository."""
    checkout = Path(__file__).resolve().parents[2]
    return str(checkout) if (checkout / ".claude-plugin" / "marketplace.json").is_file() else GITHUB_REPO


def _json_keys(path: Path, key: str | None = None) -> set[str]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    data = data.get(key, {}) if key and isinstance(data, dict) else data
    return set(data) if isinstance(data, dict) else set()


def plugin_installed() -> bool:
    return f"{PLUGIN}@{MARKETPLACE}" in _json_keys(claude_home() / "plugins" / "installed_plugins.json", "plugins")


def marketplace_known() -> bool:
    return MARKETPLACE in _json_keys(claude_home() / "plugins" / "known_marketplaces.json")


def _claude(*args: str) -> str:
    result = subprocess.run([claude_cli() or "claude", *args], check=False)
    return f"`claude {' '.join(args)}` exited {result.returncode}"


def plugin_steps(*, uninstall: bool = False) -> list[Step]:
    if not claude_cli():
        return []
    if uninstall:
        steps = []
        if plugin_installed():
            steps.append(
                Step(
                    f"uninstall the {PLUGIN} plugin (hooks)",
                    lambda: _claude("plugin", "uninstall", f"{PLUGIN}@{MARKETPLACE}"),
                )
            )
        if marketplace_known():
            steps.append(
                Step(
                    f"remove the {MARKETPLACE} plugin marketplace",
                    lambda: _claude("plugin", "marketplace", "remove", MARKETPLACE),
                )
            )
        return steps
    if plugin_installed():
        return []
    source = marketplace_source()
    known = marketplace_known()

    def install() -> str:
        results = [] if known else [_claude("plugin", "marketplace", "add", source)]
        results.append(_claude("plugin", "install", f"{PLUGIN}@{MARKETPLACE}"))
        return "; ".join(results)

    where = "" if known else f"register the {MARKETPLACE} plugin marketplace ({source}) and "
    return [
        Step(f"{where}install the {PLUGIN} plugin (format, affected-tests, guard, secrets and notify hooks)", install)
    ]


def plan(*, uninstall: bool = False) -> list[Step]:
    claude_md = claude_home() / "CLAUDE.md"
    current = claude_md.read_text() if claude_md.exists() else ""
    steps: list[Step] = []
    if uninstall:
        if START in current:

            def remove() -> str:
                backup = _backup(claude_md)
                claude_md.write_text(strip_snippet(current))
                return f"removed the claude-toolkit section from {claude_md} (backup: {backup})"

            steps.append(Step(f"remove the claude-toolkit section from {claude_md}", remove))
        return steps + plugin_steps(uninstall=True)
    wanted = with_snippet(current)
    if wanted != current:
        verb = "update" if START in current else "add"

        def write() -> str:
            backup = _backup(claude_md)
            claude_md.parent.mkdir(parents=True, exist_ok=True)
            claude_md.write_text(wanted)
            return f"{verb}d the claude-toolkit section in {claude_md}" + (f" (backup: {backup})" if backup else "")

        steps.append(Step(f"{verb} a {len(SNIPPET.splitlines())}-line claude-toolkit section in {claude_md}", write))
    steps += plugin_steps()
    host = detect_host()
    for dep in TOOLKIT_DEPENDENCIES:
        if not dep.shipped or shutil.which(dep.command):
            continue
        command = dep.hint(host)
        if not command or command.startswith("see "):
            continue

        def install(command: str = command) -> str:
            result = subprocess.run(command, shell=True, check=False)
            return f"`{command}` exited {result.returncode}"

        label = "required" if dep.required else "optional"
        steps.append(Step(f"install {dep.command} ({label}: {dep.purpose}) with `{command}`", install))
    return steps


def run(*, assume_yes: bool, dry_run: bool, uninstall: bool) -> int:
    st = Style.detect()
    steps = plan(uninstall=uninstall)
    if not steps:
        if st.enabled:
            print(f"{st.header('ctk setup')}\n\n  {st.ok('✓ already set up', bold=True)} {st.muted('· nothing to do')}")
        else:
            print("ctk setup: nothing to do")
        return 0
    if st.enabled:
        print(f"{st.header('ctk setup', 'uninstall' if uninstall else '')}\n\n  {st.accent('Plan', bold=True)}")
        for index, step in enumerate(steps, 1):
            print(f"    {st.accent(str(index))}  {step.description}")
        print()
    else:
        print("ctk setup plan:")
        for index, step in enumerate(steps, 1):
            print(f"  {index}. {step.description}")
    if dry_run:
        if st.enabled:
            print(f"  {st.muted('dry run: nothing was changed')}")
        return 0
    for step in steps:
        if confirm(f"{step.description}?", assume_yes=assume_yes):
            result = step.apply()
            print(f"  {st.ok('✓')} {result}" if st.enabled else "  " + result)
        else:
            print(f"  {st.muted('↷ skipped: ' + step.description)}" if st.enabled else f"  skipped: {step.description}")
    return 0
