"""Command-line entry point: ``ctk <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .common import EXIT_NEEDS_CONFIRMATION, ConfirmationRequired
from .style import Style


def _doctor(args: argparse.Namespace) -> int:
    from . import doctor

    report = doctor.check_toolkit() if args.toolkit else doctor.check_project(Path(args.path).resolve())
    print(doctor.to_json(report) if args.json else doctor.render(report, verbose=args.verbose))
    return 1 if report.errors else 0


def _runq(args: argparse.Namespace) -> int:
    from . import runq

    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    return runq.run(command, keep_logs=args.keep)


def _sessions(args: argparse.Namespace) -> int:
    from . import sessions
    from .style import Spinner

    root = Path(args.root).expanduser() if args.root else sessions.default_root()
    paths = sessions.find_sessions(root, args.since, include_subagents=not args.no_subagents)
    with Spinner(f"reading {len(paths)} transcripts"):
        parsed = [sessions.parse_session(path) for path in paths]
    if args.project:
        parsed = [s for s in parsed if s.project and args.project in s.project]
    if args.csv:
        text = sessions.weekly_csv(parsed)
        if args.csv == "-":
            print(text, end="")
        else:
            Path(args.csv).write_text(text)
            print(f"wrote {args.csv}")
        return 0
    summary = sessions.summarise(parsed)
    label = f"last {args.since:g} days" if args.since else "all time"
    if args.project:
        label += f" · project contains {args.project!r}"
    print(json.dumps(asdict(summary), indent=2) if args.json else sessions.render(summary, label))
    return 0


def _lsp(args: argparse.Namespace) -> int:
    from . import lsp

    root = Path(args.path).resolve()
    host = lsp.default_host()
    statuses = lsp.status(root)
    print(lsp.render(root, statuses, host))
    if args.install and any(not st.ready for st in statuses):
        for line in lsp.install(statuses, host, assume_yes=args.yes):
            print("  " + line)
    return 0 if all(st.ready for st in statuses) else 1


def _setup(args: argparse.Namespace) -> int:
    from . import setup

    return setup.run(assume_yes=args.yes, dry_run=args.dry_run, uninstall=args.uninstall)


def _hook(args: argparse.Namespace) -> int:
    if args.git:
        from .hooks.secrets import git_pre_commit

        return git_pre_commit()
    if args.log:
        from .hooks.guard import show_log

        print(show_log())
        return 0
    from . import hooks

    return hooks.run(args.hook)


OVERVIEW = (
    ("doctor", "toolchain pins vs installed versions, dependencies vs lockfiles"),
    ("runq", "run a command; print failures, summary and the full-log path"),
    ("lsp", "language servers and Claude Code LSP plugins a project needs"),
    ("sessions", "counts-only metrics from Claude Code transcripts"),
    ("setup", "wire the toolkit into Claude Code (asks before each change)"),
    ("hook", "logic behind the Claude Code plugin hooks (event JSON on stdin)"),
)
EXAMPLES = ("ctk doctor ~/project", "ctk runq -- pytest", "ctk lsp --install", "ctk sessions --since 30")
DOCS = "https://github.com/nadezhdkov/claude-toolkit"


def overview() -> str:
    """What `ctk` with no command shows."""
    st = Style.detect()
    width = max(len(name) for name, _ in OVERVIEW)
    if not st.enabled:
        lines = [f"claude-toolkit {__version__}: tools that make Claude Code more effective", "", "commands:"]
        lines += [f"  {name.ljust(width)}  {text}" for name, text in OVERVIEW]
        lines += ["", "examples:", *(f"  {example}" for example in EXAMPLES), "", f"docs: {DOCS}"]
        return "\n".join(lines)
    lines = [
        f"{st.accent('◆', bold=True)} {st.bold('claude-toolkit')} {st.muted(__version__)}",
        f"  {st.muted('Tools that make Claude Code more effective.')}",
        "",
        f"  {st.accent('Commands', bold=True)}",
        *(f"    {st.accent2(name.ljust(width))}  {text}" for name, text in OVERVIEW),
        "",
        f"  {st.accent('Examples', bold=True)}",
        *(f"    {st.command(example)}" for example in EXAMPLES),
        "",
        f"  {st.muted('Help:')} ctk <command> --help   {st.muted('Docs:')} {st.accent2(DOCS)}",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ctk", description="claude-toolkit: tools that make Claude Code more effective."
    )
    parser.add_argument("--version", action="version", version=f"ctk {__version__}")
    sub = parser.add_subparsers(dest="name", metavar="<command>")

    p = sub.add_parser("doctor", help="check toolchain pins and dependency sync")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--toolkit", action="store_true", help="check the toolkit's own dependencies instead")
    p.add_argument("--json", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true", help="also show passing checks")
    p.set_defaults(func=_doctor)

    p = sub.add_parser("runq", help="run a command and print only failures, summary and log path")
    p.add_argument("--keep", type=int, default=50, help="number of logs to keep (default 50)")
    p.add_argument("command", nargs=argparse.REMAINDER, help="-- <command> [args...]")
    p.set_defaults(func=_runq)

    p = sub.add_parser("sessions", help="usage metrics from Claude Code transcripts")
    p.add_argument("--since", type=float, metavar="DAYS", help="only sessions active in the last DAYS days")
    p.add_argument("--project", metavar="TEXT", help="only sessions whose working directory contains TEXT")
    p.add_argument("--no-subagents", action="store_true", help="ignore subagent transcripts")
    p.add_argument("--csv", metavar="FILE", help="write weekly metrics as CSV ('-' for stdout)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--root", help=argparse.SUPPRESS)
    p.set_defaults(func=_sessions)

    p = sub.add_parser("lsp", help="language servers needed by a project")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--install", action="store_true", help="install missing servers and plugins (asks first)")
    p.add_argument("-y", "--yes", action="store_true", help="answer yes to every confirmation")
    p.set_defaults(func=_lsp)

    p = sub.add_parser("setup", help="wire the toolkit into Claude Code (asks before each change)")
    p.add_argument("-y", "--yes", action="store_true", help="answer yes to every confirmation")
    p.add_argument("--dry-run", action="store_true", help="only print the plan")
    p.add_argument("--uninstall", action="store_true", help="remove what setup added")
    p.set_defaults(func=_setup)

    from .hooks import HOOKS

    p = sub.add_parser("hook", help="run a plugin hook on the event JSON read from stdin")
    p.add_argument("hook", choices=HOOKS)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--git", action="store_true", help="secrets: act as a git pre-commit hook (exit 1 on findings)")
    mode.add_argument("--log", action="store_true", help="guard-destructive: show recorded matches")
    p.set_defaults(func=_hook)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.name is None:
        print(overview())
        return 0
    try:
        return args.func(args)
    except ConfirmationRequired as needed:
        print(
            f"ctk: confirmation required ({needed}). No terminal is attached, so nothing was changed. "
            "Review the plan above and rerun with --yes to apply.",
            file=sys.stderr,
        )
        return EXIT_NEEDS_CONFIRMATION
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
