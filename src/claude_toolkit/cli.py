"""Command-line entry point: ``ctk <command>``."""

from __future__ import annotations

import argparse
import contextlib
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
    if args.compare:
        return _sessions_compare(args, root)
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
            Path(args.csv).write_text(text, encoding="utf-8")
            print(f"wrote {args.csv}")
        return 0
    summary = sessions.summarise(parsed)
    label = f"last {args.since:g} days" if args.since else "all time"
    if args.project:
        label += f" · project contains {args.project!r}"
    print(json.dumps(asdict(summary), indent=2) if args.json else sessions.render(summary, label))
    return 0


def _sessions_compare(args: argparse.Namespace, root: Path) -> int:
    import time

    from . import sessions
    from .style import Spinner

    try:
        periods = [sessions.parse_period(text) for text in args.compare]
    except ValueError as error:
        print(f"sessions: {error}", file=sys.stderr)
        return 2
    oldest_days = (time.time() - min(start for start, _ in periods)) / 86400
    paths = sessions.find_sessions(root, max(oldest_days, 0), include_subagents=not args.no_subagents)
    with Spinner(f"reading {len(paths)} transcripts"):
        parsed = [sessions.parse_session(path) for path in paths]
    if args.project:
        parsed = [s for s in parsed if s.project and args.project in s.project]
    summaries = [sessions.summarise(sessions.in_period(parsed, period)) for period in periods]
    result = sessions.compare(*summaries, labels=tuple(args.compare))
    print(json.dumps(asdict(result), indent=2) if args.json else sessions.render_comparison(result))
    return 0 if result.verdict == "pass" else 1


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

    return setup.run(
        assume_yes=args.yes,
        dry_run=args.dry_run,
        uninstall=args.uninstall,
        agents=args.agents,
        agents_files=[Path(f).expanduser() for f in args.agents_file or []],
    )


def _shoot(args: argparse.Namespace) -> int:
    from . import shoot

    return shoot.run(args)


def _audiocheck(args: argparse.Namespace) -> int:
    from . import audiocheck

    return audiocheck.run(args)


def _sandbox(args: argparse.Namespace) -> int:
    from . import sandbox

    return sandbox.run(args)


def _libdocs(args: argparse.Namespace) -> int:
    from . import libdocs

    return libdocs.run(args)


def _map(args: argparse.Namespace) -> int:
    from . import map as repo_map

    return repo_map.run(args)


def _verify(args: argparse.Namespace) -> int:
    from . import verify

    return verify.run(args)


def _diffcheck(args: argparse.Namespace) -> int:
    from . import diffcheck

    return diffcheck.run(args)


def _relay(args: argparse.Namespace) -> int:
    from . import relay

    return relay.run(args)


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
    ("shoot", "deterministic screenshots (web, Godot, desktop), baselines, contact sheets"),
    ("audiocheck", "loudness, clipping, silence and loop seams of audio files, plus images"),
    ("sandbox", "run untrusted code without network, with a read-only system and limits"),
    ("libdocs", "installed version, README and API of a dependency, from its own files"),
    ("map", "compact map of a repository's files and symbols; where a symbol is used"),
    ("verify", "what is verified for the current code: fresh, failing, stale or never run"),
    ("diffcheck", "deterministic checks of a change: removed API, risky files, debug leftovers, tests"),
    ("relay", "hand the work over to a fresh Claude Code session in a new terminal"),
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
    p.add_argument(
        "--compare",
        nargs=2,
        metavar=("BASELINE", "CURRENT"),
        help="compare two periods, START..END each (dates, or Nd days ago); exit 0 when the Phase 8 criterion is met",
    )
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
    p.add_argument(
        "--agents",
        action="store_true",
        help="offer the skills to agents other than Claude Code (~/.agents/skills) even if none is found",
    )
    p.add_argument(
        "--agents-file",
        action="append",
        metavar="FILE",
        help="add the short ctk section to this global instructions file (repeatable; pass it again to uninstall)",
    )
    p.set_defaults(func=_setup)

    p = sub.add_parser("shoot", help="deterministic screenshots, baseline comparison and contact sheets")
    kinds = p.add_subparsers(dest="kind", metavar="<kind>", required=True)
    baseline = argparse.ArgumentParser(add_help=False)
    baseline.add_argument("--baseline", metavar="PNG", help="compare with this image (created when missing)")
    baseline.add_argument("--update", action="store_true", help="overwrite the baseline with this capture")
    compare = argparse.ArgumentParser(add_help=False)
    compare.add_argument("--threshold", type=int, default=8, help="per-channel difference ignored (0-255, default 8)")
    compare.add_argument("--tolerance", type=float, default=0.1, help="%% of pixels allowed to differ (default 0.1)")
    compare.add_argument("--mask", action="append", metavar="X,Y,W,H", help="ignore a rectangle (repeatable)")
    capture = argparse.ArgumentParser(add_help=False)
    capture.add_argument("-o", "--output", metavar="PNG", help="where to write (default: the ctk cache)")
    capture.add_argument("--size", help="viewport/screen size (default 1280x720; Godot: the project's)")

    k = kinds.add_parser("web", parents=[capture, baseline, compare], help="a URL or HTML file in Chromium")
    k.add_argument("target", help="URL, host:port or path to an HTML file")
    k.add_argument("--scale", type=float, default=1, help="device scale factor (default 1)")
    k.add_argument("--full-page", action="store_true")
    k.add_argument("--wait-for", metavar="SELECTOR", help="wait for this CSS selector before capturing")
    k.add_argument("--delay", type=int, default=0, metavar="MS", help="extra wait after load")
    k.add_argument("--mask-selector", action="append", metavar="SELECTOR", help="paint over elements (repeatable)")
    k.add_argument("--dark", action="store_true", help="prefers-color-scheme: dark")
    k.add_argument("--timeout", type=float, default=30, help="seconds for load and selectors (default 30)")
    k.add_argument("-y", "--yes", action="store_true", help="install the browser without asking if missing")

    k = kinds.add_parser("godot", parents=[capture, baseline, compare], help="a Godot 4 project or scene")
    k.add_argument("project", nargs="?", default=".", help="directory with project.godot (default .)")
    k.add_argument("--scene", metavar="RES", help="scene to run, e.g. res://ui/menu.tscn (default: main scene)")
    k.add_argument("--frames", type=int, default=60, help="frames to run at 60 fps before capturing (default 60)")

    k = kinds.add_parser("desktop", parents=[capture, baseline, compare], help="any program on a private Xvfb display")
    k.add_argument("--delay", type=float, default=2, help="seconds to wait before capturing (default 2)")
    k.add_argument("command", nargs=argparse.REMAINDER, help="-- <command> [args...]")

    k = kinds.add_parser("compare", parents=[compare], help="compare two PNG files")
    k.add_argument("baseline_image", metavar="baseline")
    k.add_argument("actual")
    k.add_argument("--diff", metavar="PNG", help="where to write the diff image")

    k = kinds.add_parser("sheet", help="contact sheet of several PNG files")
    k.add_argument("images", nargs="+")
    k.add_argument("-o", "--output", metavar="PNG")
    k.add_argument("--columns", type=int, default=3)
    k.add_argument("--thumb-width", type=int, default=400)
    p.set_defaults(func=_shoot)

    p = sub.add_parser("audiocheck", help="loudness, clipping, silence and loop seams of audio files")
    p.add_argument("paths", nargs="+", help="audio files or directories (searched recursively)")
    p.add_argument("--target", type=float, metavar="LUFS", help="required integrated loudness, e.g. -16")
    p.add_argument("--lufs-tolerance", type=float, default=1.0, metavar="LU", help="allowed distance (default 1)")
    p.add_argument("--max-true-peak", type=float, default=-1.0, metavar="DBTP", help="warn above (default -1)")
    p.add_argument("--max-lead", type=float, default=0.1, metavar="S", help="leading silence warning (default 0.1)")
    p.add_argument("--max-trail", type=float, default=1.0, metavar="S", help="trailing silence warning (default 1)")
    p.add_argument("--max-gap", type=float, default=2.0, metavar="S", help="report inner silences this long")
    p.add_argument("--silence-db", type=float, default=-60.0, metavar="DB", help="silence threshold (default -60)")
    p.add_argument("--loop", action="store_true", help="check the loop point (end back to start)")
    p.add_argument("--images", nargs="?", const="", metavar="DIR", help="write waveform and spectrogram PNGs")
    p.add_argument("--strict", action="store_true", help="warnings also fail (exit 1)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_audiocheck)

    p = sub.add_parser("sandbox", help="run a command in a bubblewrap sandbox (no network, limits)")
    p.add_argument("--dir", default=".", help="directory mounted read-write (default .)")
    p.add_argument("--read-only", action="store_true", help="mount the directory read-only")
    p.add_argument("--net", action="store_true", help="allow network access")
    p.add_argument("--ro", action="append", metavar="PATH", help="also mount PATH read-only (repeatable)")
    p.add_argument("--rw", action="append", metavar="PATH", help="also mount PATH read-write (repeatable)")
    p.add_argument("--env", action="append", metavar="NAME[=VALUE]", help="pass an environment variable")
    p.add_argument("--no-toolchains", action="store_true", help="hide toolchains installed under the home")
    p.add_argument("--memory", help="memory limit (default: half the RAM, at most 4G)")
    p.add_argument("--tmp-size", help="size of /tmp and of the home tmpfs, which use RAM (default: RAM/8, at most 1G)")
    p.add_argument("--cpus", type=float, help="CPU limit in cores (default 2)")
    p.add_argument("--pids", type=int, help="process limit (default 512)")
    p.add_argument("--timeout", type=float, metavar="S", help="wall-clock limit in seconds (default 600)")
    p.add_argument("--dry-run", action="store_true", help="print the sandbox and the bwrap command only")
    p.add_argument("command", nargs=argparse.REMAINDER, help="-- <command> [args...]")
    p.set_defaults(func=_sandbox)

    p = sub.add_parser("libdocs", help="installed version, README and API of a dependency")
    p.add_argument("package", help="package name (PyPI/import name, npm name, crate or Go module path)")
    p.add_argument("path", nargs="?", default=".", help="project directory (default .)")
    p.add_argument("--ecosystem", choices=("python", "node", "rust", "go"), help="only look in one ecosystem")
    view = p.add_mutually_exclusive_group()
    view.add_argument("--readme", action="store_true", help="print the README")
    view.add_argument("--api", action="store_true", help="print the whole public API (not just the first lines)")
    view.add_argument("--find", metavar="SYMBOL", help="where SYMBOL (e.g. Session.get) is defined, with its docs")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_libdocs)

    p = sub.add_parser("map", help="compact map of files and symbols, ranked by use; --uses for one symbol")
    p.add_argument("path", nargs="?", default=".", help="repository directory (default .)")
    p.add_argument("--budget", type=int, default=120, metavar="LINES", help="maximum lines (default 120)")
    p.add_argument("--uses", metavar="SYMBOL", help="where SYMBOL is defined and used, and which tests touch it")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_map)

    p = sub.add_parser("verify", help="checks recorded for the current code state; `run` runs the project's checks")
    p.add_argument("action", nargs="?", choices=("status", "run"), default="status")
    p.add_argument("--path", default=".", help="directory inside the repository (default .)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_verify)

    p = sub.add_parser("diffcheck", help="deterministic checks of the current change against a base")
    p.add_argument("--base", help="commit to compare with (default: merge-base with the default branch)")
    p.add_argument("--path", default=".", help="directory inside the repository (default .)")
    p.add_argument("--strict", action="store_true", help="exit 1 on any finding, not only high ones")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_diffcheck)

    p = sub.add_parser("relay", help="hand the work over to a fresh Claude Code session in a new terminal")
    action = p.add_mutually_exclusive_group()
    action.add_argument("--show", action="store_true", help="print what the new session starts from, and stop")
    action.add_argument("--release", action="store_true", help="let a relayed session edit again")
    p.add_argument("--session", metavar="ID", help="the session handing over (default: $CLAUDE_CODE_SESSION_ID)")
    p.add_argument("--terminal", help="terminal to open (default: [relay] terminal, else detected)")
    p.add_argument("--force", action="store_true", help="relay even without a fresh handoff file")
    p.add_argument("--dry-run", action="store_true", help="show the command and change nothing")
    p.add_argument("--yes", action="store_true", help="open the new session without asking")
    p.set_defaults(func=_relay)

    from .hooks import HOOKS

    p = sub.add_parser("hook", help="run a plugin hook on the event JSON read from stdin")
    p.add_argument("hook", choices=HOOKS)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--git", action="store_true", help="secrets: act as a git pre-commit hook (exit 1 on findings)")
    mode.add_argument("--log", action="store_true", help="guard-destructive: show recorded matches")
    p.set_defaults(func=_hook)
    return parser


def _utf8_output() -> None:
    """Windows consoles and pipes default to a legacy code page that cannot print ✓, → or ·."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure and (getattr(stream, "encoding", "") or "").lower().replace("-", "") != "utf8":
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
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
