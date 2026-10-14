"""``ctk setup``: wire the toolkit into Claude Code, always asking first.

Steps are planned, shown, then applied one by one after confirmation:
1. add a short section to ``~/.claude/CLAUDE.md`` between markers, with a backup;
2. register this repository as a plugin marketplace and install the ``ctk``
   plugin (the hooks) with the ``claude`` CLI;
3. offer to install missing toolkit dependencies;
4. for agents other than Claude Code (``--agents``, or when one is found): copy the process skills to
   ``~/.agents/skills`` and, into the files named with ``--agents-file``, add the same short section.
``ctk setup --uninstall`` removes what it added again.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .common import confirm, detect_host
from .doctor import TOOLKIT_DEPENDENCIES
from .style import Style

PLUGIN = "ctk"
MARKETPLACE = "ctk"
GITHUB_REPO = "nadezhdkov/claude-toolkit"
START = "<!-- claude-toolkit:start -->"
END = "<!-- claude-toolkit:end -->"

SKILL_MARK = ".claude-toolkit"  # inside each skill folder setup wrote: only those are ever replaced or removed
PROJECT_ONLY = {"issue"}  # skills for this repository's maintainers, not for everyone's machine
OTHER_AGENTS = (
    ("Codex", ".codex"),
    ("Gemini CLI", ".gemini"),
    ("opencode", ".config/opencode"),
    ("~/.agents", ".agents"),
)

PAST = {"add": "added", "update": "updated"}

_BODY = """## claude-toolkit

Use these `ctk` commands instead of ad-hoc scripts:

- `ctk doctor [path]`: toolchain and dependency check; run it first when a build or test fails oddly.
- `ctk runq -- <cmd>`: long test, build or lint output reduced to failures, summary and log path.
- `ctk verify [run]`: what is verified for the code as it is now; never claim checks pass without a fresh ✓ there.
- `ctk map [path]`, `ctk map --uses NAME`: repository map before exploring; where a symbol is used.
- `ctk libdocs <pkg> [--find SYMBOL]`: installed version and real API of a dependency, before using it.
- `ctk shoot web|godot|desktop`: screenshot after a UI change (`--baseline` compares); `ctk audiocheck <files>` for audio.
- `ctk sandbox -- <cmd>`: run untrusted code without network, with a read-only system.
"""
_HOOKS = "If a ctk hook blocks a command or reports failing tests, fix the cause or ask the user. "
_ASKS = "Commands that change the system ask first; without a terminal they exit 3: show the plan, rerun with `--yes` only after approval."
SNIPPET = f"{START}\n{_BODY}\n{_HOOKS}{_ASKS}\n{END}\n"  # Claude Code: it has the plugin's hooks
AGENTS_SNIPPET = f"{START}\n{_BODY}\n{_ASKS}\n{END}\n"  # other agents: no hooks


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


def with_snippet(text: str, snippet: str = SNIPPET) -> str:
    """Idempotently insert or refresh the section at the end of CLAUDE.md (or another instructions file)."""
    base = strip_snippet(text).rstrip("\n")
    return (base + "\n\n" if base else "") + snippet


def claude_cli() -> str | None:
    return shutil.which("claude")


def marketplace_source() -> str:
    """This checkout when ctk runs from one (editable install), otherwise the GitHub repository."""
    checkout = Path(__file__).resolve().parents[2]
    return str(checkout) if (checkout / ".claude-plugin" / "marketplace.json").is_file() else GITHUB_REPO


def _json_keys(path: Path, key: str | None = None) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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


# --- Agents other than Claude Code ----------------------------------------------------------------


def agent_home() -> Path:
    return Path.home()


def other_agents() -> list[str]:
    """Agents whose configuration folder exists on this machine."""
    return [name for name, folder in OTHER_AGENTS if (agent_home() / folder).is_dir()]


def skills_source() -> Path | None:
    """The skills to copy: shipped inside the package, else this checkout's ``.agents/skills``."""
    here = Path(__file__).resolve()
    for candidate in (here.parent / "agent_skills", here.parents[2] / ".agents" / "skills"):
        if candidate.is_dir() and any(candidate.glob("*/SKILL.md")):
            return candidate
    return None


def _files(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name != SKILL_MARK
    }


def skill_state(source: Path, target: Path) -> str:
    """new | update | current | foreign (a folder of that name that is not ours)."""
    if not target.exists():
        return "new"
    if not (target / SKILL_MARK).is_file():
        return "foreign"
    return "current" if _files(source) == _files(target) else "update"


def agent_skill_steps(*, uninstall: bool = False, offer: bool = False) -> list[Step]:
    root = agent_home() / ".agents" / "skills"
    if uninstall:
        ours = [d for d in sorted(root.glob("*")) if (d / SKILL_MARK).is_file()] if root.is_dir() else []
        if not ours:
            return []

        def remove() -> str:
            for folder in ours:
                shutil.rmtree(folder)
            return f"removed {len(ours)} claude-toolkit skill(s) from {root}"

        return [
            Step(
                f"remove the {len(ours)} claude-toolkit skills ({', '.join(d.name for d in ours)}) from {root}", remove
            )
        ]
    source = skills_source()
    detected = other_agents()
    if source is None or not (offer or detected):
        return []
    skills = [d for d in sorted(source.iterdir()) if (d / "SKILL.md").is_file() and d.name not in PROJECT_ONLY]
    states = {d.name: skill_state(d, root / d.name) for d in skills}
    todo = [d for d in skills if states[d.name] in ("new", "update")]
    if not todo:
        return []
    kept = [name for name, state in states.items() if state == "foreign"]

    def install() -> str:
        for folder in todo:
            target = root / folder.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(folder, target)
            (target / SKILL_MARK).write_text(f"claude-toolkit {__version__}\n", encoding="utf-8")
        return f"copied {len(todo)} skill(s) to {root}" + (f"; kept your own {', '.join(kept)}" if kept else "")

    who = f" ({', '.join(detected)} found)" if detected else ""
    names = ", ".join(d.name for d in todo)
    note = f"; your own {', '.join(kept)} stay untouched" if kept else ""
    return [Step(f"copy the process skills ({names}) to {root} for agents other than Claude Code{who}{note}", install)]


def _backup_beside(path: Path) -> Path | None:
    if not path.exists():
        return None
    target = path.with_name(f"{path.name}.claude-toolkit-backup-{time.strftime('%Y%m%d-%H%M%S')}")
    target.write_bytes(path.read_bytes())
    return target


def instruction_steps(files: list[Path], *, uninstall: bool = False) -> list[Step]:
    """Add (or remove) the short section in the global instructions files the user named."""
    steps = []
    for path in files:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if uninstall:
            if START not in current:
                continue

            def remove(path: Path = path, current: str = current) -> str:
                backup = _backup_beside(path)
                path.write_text(strip_snippet(current), encoding="utf-8")
                return f"removed the claude-toolkit section from {path} (backup: {backup})"

            steps.append(Step(f"remove the claude-toolkit section from {path}", remove))
            continue
        wanted = with_snippet(current, AGENTS_SNIPPET)
        if wanted == current:
            continue
        verb = "update" if START in current else "add"

        def write(path: Path = path, wanted: str = wanted, verb: str = verb) -> str:
            backup = _backup_beside(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(wanted, encoding="utf-8")
            return f"{PAST[verb]} the claude-toolkit section in {path}" + (f" (backup: {backup})" if backup else "")

        steps.append(Step(f"{verb} a {len(AGENTS_SNIPPET.splitlines())}-line claude-toolkit section in {path}", write))
    return steps


def plan(*, uninstall: bool = False, agents: bool = False, agents_files: list[Path] | None = None) -> list[Step]:
    others = agent_skill_steps(uninstall=uninstall, offer=agents) + instruction_steps(
        agents_files or [], uninstall=uninstall
    )
    claude_md = claude_home() / "CLAUDE.md"
    current = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
    steps: list[Step] = []
    if uninstall:
        if START in current:

            def remove() -> str:
                backup = _backup(claude_md)
                claude_md.write_text(strip_snippet(current), encoding="utf-8")
                return f"removed the claude-toolkit section from {claude_md} (backup: {backup})"

            steps.append(Step(f"remove the claude-toolkit section from {claude_md}", remove))
        return steps + plugin_steps(uninstall=True) + others
    wanted = with_snippet(current)
    if wanted != current:
        verb = "update" if START in current else "add"

        def write() -> str:
            backup = _backup(claude_md)
            claude_md.parent.mkdir(parents=True, exist_ok=True)
            claude_md.write_text(wanted, encoding="utf-8")
            return f"{PAST[verb]} the claude-toolkit section in {claude_md}" + (
                f" (backup: {backup})" if backup else ""
            )

        steps.append(Step(f"{verb} a {len(SNIPPET.splitlines())}-line claude-toolkit section in {claude_md}", write))
    steps += plugin_steps() + others
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


def run(
    *,
    assume_yes: bool,
    dry_run: bool,
    uninstall: bool,
    agents: bool = False,
    agents_files: list[Path] | None = None,
) -> int:
    st = Style.detect()
    steps = plan(uninstall=uninstall, agents=agents, agents_files=agents_files)
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
