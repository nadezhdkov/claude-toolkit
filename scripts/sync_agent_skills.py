#!/usr/bin/env python3
"""Mirror the skills into .agents/skills/, where agents other than Claude Code look for them.

    scripts/sync_agent_skills.py           write the mirror
    scripts/sync_agent_skills.py --check   exit 1 when the mirror is out of date

Sources: plugin/skills/ (the `ctk` plugin) and .claude/skills/ (this project's own). Files are copied, not
linked, so a Windows checkout works. `orchestrate` stays out: it delegates to Claude Code's subagents.
Standard library only.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("plugin/skills", ".claude/skills")
TARGET = ".agents/skills"
CLAUDE_ONLY = {"orchestrate"}
README = """# Agent skills

A mirror of the skills of this repository for agents other than Claude Code (the open
`SKILL.md` layout). **Do not edit it**: change the source in `plugin/skills/` or `.claude/skills/` and run
`make skills`; CI fails when the mirror is out of date.

The skills call `ctk` (see the README for the install) and refer to `AGENTS.md`. `orchestrate` is not here: it
delegates to Claude Code's subagents.
"""


def expected(root: Path) -> dict[str, bytes]:
    """Relative path under the target -> content, for every file the mirror must hold."""
    files = {"README.md": README.encode()}
    for source in SOURCES:
        for skill in sorted((root / source).glob("*/SKILL.md")):
            folder = skill.parent
            if folder.name in CLAUDE_ONLY:
                continue
            for path in sorted(p for p in folder.rglob("*") if p.is_file()):
                files[f"{folder.name}/{path.relative_to(folder).as_posix()}"] = path.read_bytes()
    return files


def current(root: Path) -> dict[str, bytes]:
    base = root / TARGET
    return (
        {p.relative_to(base).as_posix(): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}
        if base.is_dir()
        else {}
    )


def differences(root: Path) -> list[str]:
    want, have = expected(root), current(root)
    return (
        [f"missing {name}" for name in want if name not in have]
        + [f"stale {name}" for name in have if name not in want]
        + [f"differs {name}" for name in want if name in have and want[name] != have[name]]
    )


def write(root: Path) -> list[str]:
    problems = differences(root)
    base = root / TARGET
    if base.exists():
        shutil.rmtree(base)
    for name, data in expected(root).items():
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.check:
        problems = differences(args.root)
        print("\n".join(problems) if problems else f"{TARGET} is up to date")
        if problems:
            print("run `make skills`", file=sys.stderr)
        return 1 if problems else 0
    changed = write(args.root)
    print(
        f"{TARGET}: {len(expected(args.root)) - 1} skill file(s) written"
        + (f", {len(changed)} changed" if changed else ", no change")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
