#!/usr/bin/env python3
"""Release automation: the next version from Conventional Commits, every version file updated together.

    scripts/release.py status            what would be released, and why
    scripts/release.py next              the next version (exit 1 when there is nothing to release)
    scripts/release.py version           the version the files declare now
    scripts/release.py check             all version files agree and every changelog fragment is well named
    scripts/release.py changelog         what [Unreleased] will hold at the next release (entries + fragments)
    scripts/release.py prepare [--version X.Y.Z]   write the version into the files and cut the changelog
    scripts/release.py notes [X.Y.Z]     the changelog section of a version, for the GitHub release
    scripts/release.py pr [--yes]        prepare the release in a new worktree and open the pull request

Standard library only. Rules (docs/releasing.md): feat -> minor, fix/perf/revert -> patch, a `!` or a
BREAKING CHANGE footer -> major (minor while the major version is 0); other types do not release by
themselves. `chore: release` commits and merge commits are ignored.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = r"\d+\.\d+\.\d+"
COMMIT = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?: (?P<text>.+)$")
LEVELS = {"feat": "minor", "fix": "patch", "perf": "patch", "revert": "patch"}
ORDER = ("patch", "minor", "major")


class ReleaseError(Exception):
    pass


# --- Versions in files ------------------------------------------------------------------------
# (file, pattern with the version as group 2): the one place each file declares it.
FILES = (
    ("pyproject.toml", rf'(?m)^(version = ")({VERSION})(")'),
    ("src/claude_toolkit/__init__.py", rf'(?m)^(__version__ = ")({VERSION})(")'),
    ("uv.lock", rf'(name = "claude-toolkit"\nversion = ")({VERSION})(")'),
    ("plugin/.claude-plugin/plugin.json", rf'("version": ")({VERSION})(")'),
)
CHANGELOG = "docs/CHANGELOG.md"
# A pull request adds docs/changelog.d/<slug>.<category>.md instead of editing CHANGELOG.md, where every
# pull request would write in the same place and conflict with the others. A release folds them in.
FRAGMENTS = "docs/changelog.d"
CATEGORIES = ("added", "changed", "deprecated", "removed", "fixed", "security")
CONFLICT_MARKER = re.compile(r"(?m)^(<<<<<<< |>>>>>>> )")  # a half-resolved merge, which would reach the release notes
FRAGMENT = re.compile(rf"^[A-Za-z0-9][\w.-]*\.({'|'.join(CATEGORIES)})\.md$")


def declared(root: Path) -> dict[str, str]:
    found = {}
    for name, pattern in FILES:
        match = re.search(pattern, (root / name).read_text(encoding="utf-8"))
        if not match:
            raise ReleaseError(f"{name}: no version found")
        found[name] = match.group(2)
    released = re.search(rf"(?m)^## \[({VERSION})\]", (root / CHANGELOG).read_text(encoding="utf-8"))
    if not released:
        raise ReleaseError(f"{CHANGELOG}: no released version found")
    found[CHANGELOG] = released.group(1)
    return found


def fragment_files(root: Path) -> list[Path]:
    folder = root / FRAGMENTS
    return sorted(p for p in folder.glob("*.md") if p.name != "README.md") if folder.is_dir() else []


def entry_text(text: str) -> str:
    """A fragment as a changelog bullet: text without a leading "- " is turned into one."""
    lines = text.strip().splitlines()
    if not lines:
        return ""
    if lines[0].startswith("- "):
        return "\n".join(line.rstrip() for line in lines)
    return "- " + lines[0].rstrip() + "".join(f"\n  {line}".rstrip() for line in lines[1:])


def fragments(root: Path) -> dict[str, list[str]]:
    """Category -> the entries waiting for the next release, in file name order."""
    found: dict[str, list[str]] = {}
    for path in fragment_files(root):
        match = FRAGMENT.match(path.name)
        entry = entry_text(path.read_text(encoding="utf-8"))
        if match and entry:
            found.setdefault(match.group(1), []).append(entry)
    return found


def check(root: Path) -> list[str]:
    """Problems: files that disagree with pyproject.toml, and fragments that would be ignored."""
    found = declared(root)
    expected = found["pyproject.toml"]
    problems = [
        f"{name} has {version}, pyproject.toml has {expected}" for name, version in found.items() if version != expected
    ]
    for path in [root / CHANGELOG, *fragment_files(root)]:
        if CONFLICT_MARKER.search(path.read_text(encoding="utf-8")):
            problems.append(f"{path.relative_to(root).as_posix()} has merge conflict markers")
    for path in fragment_files(root):
        if not FRAGMENT.match(path.name):
            problems.append(f"{FRAGMENTS}/{path.name}: name it <slug>.<{'|'.join(CATEGORIES)}>.md")
        elif not path.read_text(encoding="utf-8").strip():
            problems.append(f"{FRAGMENTS}/{path.name} is empty")
    return problems


# --- Versions from commits --------------------------------------------------------------------


def parse_version(text: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in text.split("."))  # type: ignore[return-value]


def git(root: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", check=False
    )
    if check and done.returncode:
        raise ReleaseError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


def last_tag(root: Path) -> str | None:
    tags = [t for t in git(root, "tag", "--list", "v*").split() if re.fullmatch(rf"v{VERSION}", t)]
    return max(tags, key=lambda t: parse_version(t[1:]), default=None)


def commits_since(root: Path, tag: str | None) -> list[tuple[str, str]]:
    """(subject, body) of the non-merge commits since ``tag``."""
    log = git(root, "log", "--no-merges", "--format=%x1e%s%x1f%b", f"{tag}..HEAD" if tag else "HEAD")
    commits = []
    for record in log.split("\x1e"):  # the control characters count as whitespace to str.strip(): partition first
        subject, _, body = record.partition("\x1f")
        if subject.strip() and not subject.startswith("chore: release"):
            commits.append((subject.strip(), body.strip()))
    return commits


def level_of(commits: list[tuple[str, str]]) -> tuple[str | None, list[str]]:
    """The strongest bump the commits call for, and the commits that call for it."""
    best, reasons = -1, []
    for subject, body in commits:
        match = COMMIT.match(subject)
        if not match:
            continue
        breaking = bool(match["bang"]) or bool(re.search(r"(?m)^BREAKING[ -]CHANGE:", body))
        level = "major" if breaking else LEVELS.get(match["type"])
        if level is None:
            continue
        rank = ORDER.index(level)
        if rank > best:
            best, reasons = rank, []
        if rank == best:
            reasons.append(subject)
    return (ORDER[best] if best >= 0 else None), reasons


def bump(current: str, level: str) -> str:
    major, minor, patch = parse_version(current)
    if level == "major" and major > 0:
        return f"{major + 1}.0.0"
    if level in ("major", "minor"):  # before 1.0.0 a breaking change is a minor bump
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def plan(root: Path) -> dict:
    """What the next release would be; ``next`` is None with the reason in ``why`` when there is none."""
    problems = check(root)
    current = declared(root)["pyproject.toml"]
    tag = last_tag(root)
    result = {
        "current": current,
        "last_tag": tag,
        "next": None,
        "level": None,
        "commits": [],
        "why": "",
        "fragments": len(fragment_files(root)),
    }
    if problems:
        result["why"] = "version files disagree: " + "; ".join(problems)
    elif tag is None or parse_version(current) > parse_version(tag[1:]):
        result["why"] = f"{current} is prepared but not tagged yet: its release is on its way"
    else:
        level, reasons = level_of(commits_since(root, tag))
        result["commits"] = reasons
        if level is None:
            result["why"] = f"no feat, fix, perf or breaking commit since {tag}"
        else:
            result["level"], result["next"] = level, bump(current, level)
    return result


# --- Changelog ---------------------------------------------------------------------------------


def merge_fragments(body: str, new: dict[str, list[str]]) -> str:
    """Add the fragments to the ### sections of ``body`` (creating the missing ones, in the usual order)."""
    parts = re.split(r"(?m)^### (.+)$", body)
    preamble, sections = parts[0].strip(), list(zip(parts[1::2], parts[2::2], strict=True))
    titles = {title.strip().lower(): index for index, (title, _) in enumerate(sections)}
    contents = [[title.strip(), content.strip()] for title, content in sections]
    for category in CATEGORIES:
        if category not in new:
            continue
        entries = "\n".join(new[category])
        if category in titles:
            contents[titles[category]][1] = (contents[titles[category]][1] + "\n" + entries).strip()
        else:
            contents.append([category.capitalize(), entries])
    rank = {category.capitalize(): index for index, category in enumerate(CATEGORIES)}
    contents.sort(key=lambda item: rank.get(item[0], len(rank)))  # stable: unknown headings keep their order, last
    blocks = ([preamble] if preamble else []) + [f"### {title}\n\n{content}" for title, content in contents]
    return "\n\n".join(blocks)


def unreleased(root: Path) -> str:
    """What the next release will list: the entries written in [Unreleased] plus the fragments."""
    text = (root / CHANGELOG).read_text(encoding="utf-8")
    match = re.search(r"(?ms)^## \[Unreleased\]\n(.*?)(?=^## \[|\Z)", text)
    body = re.split(r"(?m)^\[Unreleased\]: ", match.group(1))[0].strip() if match else ""
    return merge_fragments(body, fragments(root)) if fragments(root) else body


def cut_changelog(text: str, version: str, date: str, new: dict[str, list[str]] | None = None) -> str:
    """Move the [Unreleased] entries (and the fragments) under a new version heading; fix the compare links."""
    match = re.search(r"(?ms)^## \[Unreleased\]\n(.*?)(?=^## \[|\Z)", text)
    if not match:
        raise ReleaseError(f"{CHANGELOG}: no [Unreleased] section")
    body = re.split(r"(?m)^\[Unreleased\]: ", match.group(1))[0].strip()
    if new:
        body = merge_fragments(body, new)
    if not body:
        raise ReleaseError(
            f"{CHANGELOG}: [Unreleased] is empty; add the entries of this release first ({FRAGMENTS}/<slug>.added.md)"
        )
    text = text[: match.start()] + f"## [Unreleased]\n\n## [{version}] - {date}\n\n{body}\n\n" + text[match.end() :]
    link = re.search(rf"(?m)^\[Unreleased\]: (\S+)/compare/v({VERSION})\.\.\.HEAD$", text)
    if not link:
        raise ReleaseError(f"{CHANGELOG}: no [Unreleased] compare link")
    repo, previous = link.group(1), link.group(2)
    new = f"[Unreleased]: {repo}/compare/v{version}...HEAD\n[{version}]: {repo}/compare/v{previous}...v{version}"
    return text[: link.start()] + new + text[link.end() :]


def notes(root: Path, version: str) -> str:
    text = (root / CHANGELOG).read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[Unreleased\]: |\Z)", text)
    if not match or not match.group(1).strip():
        raise ReleaseError(f"{CHANGELOG}: no section for {version}")
    return match.group(1).strip() + "\n"


# --- Preparing a release -----------------------------------------------------------------------


def prepare(root: Path, version: str, date: str) -> list[str]:
    """Write ``version`` into every file and cut the changelog; returns the files changed."""
    if not re.fullmatch(VERSION, version):
        raise ReleaseError(f"not a version: {version}")
    current = declared(root)["pyproject.toml"]
    if parse_version(version) <= parse_version(current):
        raise ReleaseError(f"{version} is not newer than {current}")
    # Compute every new text first: a release that fails half way must leave nothing changed.
    writes = {CHANGELOG: cut_changelog((root / CHANGELOG).read_text(encoding="utf-8"), version, date, fragments(root))}
    for name, pattern in FILES:
        text = (root / name).read_text(encoding="utf-8")
        writes[name] = re.sub(pattern, rf"\g<1>{version}\g<3>", text, count=1)
    for name, text in writes.items():
        (root / name).write_text(text, encoding="utf-8")
    folded = fragment_files(root)
    for path in folded:
        path.unlink()
    return (
        [name for name, _ in FILES]
        + [CHANGELOG]
        + ([f"{len(folded)} changelog fragment(s) folded in"] if folded else [])
    )


def refresh_overview(root: Path) -> None:
    """The overview screenshot shows the version; the other screenshots hold timestamps, so only it is kept."""
    folder = root / "docs" / "assets" / "screenshots"
    others = {p: p.read_bytes() for p in folder.glob("*.svg") if p.name != "overview.svg"}
    subprocess.run([sys.executable, "scripts/make_screenshots.py"], cwd=root, check=True, capture_output=True)
    for path, data in others.items():
        path.write_bytes(data)


def run_pr(root: Path, assume_yes: bool, dry_run: bool) -> int:
    result = plan(root)
    if not result["next"]:
        print(f"release: nothing to release: {result['why']}")
        return 1
    version = result["next"]
    worktree = root.parent / f"{root.name}-release-{version}"
    print(f"release: {result['current']} -> {version} ({result['level']}) since {result['last_tag']}")
    for subject in result["commits"]:
        print(f"  {subject}")
    print(f"plan: worktree {worktree} from origin/main, branch release/{version}, commit, push, pull request")
    if dry_run:
        return 0
    if not assume_yes:
        if not sys.stdin.isatty():
            print("release: confirmation required and no terminal; rerun with --yes", file=sys.stderr)
            return 3
        if input("Open the release pull request? [y/N] ").strip().lower() not in ("y", "yes", "s", "sim"):
            print("release: cancelled, nothing changed")
            return 1
    git(root, "fetch", "--quiet", "origin")
    if git(root, "rev-parse", "HEAD") != git(root, "rev-parse", "origin/main"):
        print(
            "release: this checkout is not at origin/main; the release is built on it. git pull on main first.",
            file=sys.stderr,
        )
        return 1
    git(root, "worktree", "add", str(worktree), "-b", f"release/{version}", "origin/main")
    prepare(worktree, version, dt.date.today().isoformat())
    refresh_overview(worktree)
    git(worktree, "add", "-A")
    git(
        worktree,
        "commit",
        "-m",
        f"chore: release {version}\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>",
    )
    git(worktree, "push", "--set-upstream", "origin", f"release/{version}")
    body = f"Release {version} ({result['level']}), from:\n\n" + "\n".join(f"- {s}" for s in result["commits"])
    body += (
        "\n\nMerging this tags `v" + version + "` and publishes the GitHub release (`.github/workflows/release.yml`)."
    )
    done = subprocess.run(
        ["gh", "pr", "create", "--title", f"chore: release {version}", "--body", body], cwd=worktree, check=False
    )
    print(f"release: worktree {worktree}")
    return done.returncode


# --- Command line ---------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    for name in ("next", "version", "check", "changelog"):
        sub.add_parser(name)
    p = sub.add_parser("prepare")
    p.add_argument("--version")
    p.add_argument("--date", default=dt.date.today().isoformat())
    p.add_argument("--no-screenshot", action="store_true")
    sub.add_parser("notes").add_argument("version", nargs="?")
    p = sub.add_parser("pr")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    root = args.root
    try:
        if args.command == "status":
            result = plan(root)
            if args.json:
                print(json.dumps(result))
            else:
                print(f"version {result['current']} · last tag {result['last_tag']}")
                if result["next"]:
                    print(f"next    {result['next']} ({result['level']})")
                    print("\n".join(f"  {subject}" for subject in result["commits"]))
                else:
                    print(f"next    none: {result['why']}")
                print(f"changelog fragments waiting: {result['fragments']}")
            return 0
        if args.command == "next":
            result = plan(root)
            if result["next"]:
                print(result["next"])
            else:
                print(result["why"], file=sys.stderr)
            return 0 if result["next"] else 1
        if args.command == "changelog":
            print(unreleased(root) or "(nothing yet)")
            return 0
        if args.command == "version":
            print(declared(root)["pyproject.toml"])
            return 0
        if args.command == "check":
            problems = check(root)
            print("\n".join(problems) if problems else "version files agree")
            return 1 if problems else 0
        if args.command == "prepare":
            version = args.version or plan(root)["next"]
            if not version:
                raise ReleaseError("nothing to release: " + plan(root)["why"])
            changed = prepare(root, version, args.date)
            if not args.no_screenshot:
                refresh_overview(root)
            print(f"release {version}: updated " + ", ".join(changed))
            return 0
        if args.command == "notes":
            print(notes(root, args.version or declared(root)["pyproject.toml"]), end="")
            return 0
        return run_pr(root, args.yes, args.dry_run)
    except ReleaseError as error:
        print(f"release: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
