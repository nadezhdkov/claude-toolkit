"""``ctk sessions``: usage metrics from Claude Code transcripts.

Reads ``~/.claude/projects/**.jsonl`` and reports counts only: tool calls,
tool errors, exploration before the first edit, command output sizes,
"file changed on disk" notices and use of skills, subagents, MCP servers and
``ctk`` itself. Message text is never copied into the output.
"""

from __future__ import annotations

import csv
import io
import json
import re
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import COMMANDS
from .style import Style

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
EXPLORE_TOOLS = {"Read", "Grep", "Glob", "LSP"}
EXPLORE_COMMANDS = {"cat", "head", "tail", "sed", "grep", "rg", "find", "fd", "ls", "tree", "wc"}
# Cheap substring filter: only lines that can carry a metric are JSON-decoded.
CTK_COMMAND = re.compile(r"(?:^|[\s;&|(])ctk\s+([a-z][a-z-]*)")
INTERESTING = ('"tool_use"', '"tool_result"', '"edited_text_file"', '"timestamp"')


@dataclass
class Session:
    path: str
    project: str | None = None
    subagent: bool = False
    start: float | None = None
    end: float | None = None
    tool_calls: Counter = field(default_factory=Counter)
    tool_errors: int = 0
    explore_before_edit: int | None = None
    reads_before_edit: int | None = None
    bash_output_chars: list[int] = field(default_factory=list)
    result_chars: int = 0
    changed_on_disk: int = 0
    skills: Counter = field(default_factory=Counter)
    subagents: Counter = field(default_factory=Counter)
    mcp_servers: Counter = field(default_factory=Counter)
    ctk_commands: Counter = field(default_factory=Counter)


def default_root() -> Path:
    return Path.home() / ".claude" / "projects"


def _timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _result_length(content) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(item.get("text", "")) for item in content if isinstance(item, dict))
    return 0


def _first_word(command: str) -> str:
    stripped = command.strip()
    for prefix in ("cd ", "sudo "):
        if stripped.startswith(prefix) and "&&" in stripped:
            stripped = stripped.split("&&", 1)[1].strip()
    return stripped.split(" ", 1)[0].rsplit("/", 1)[-1] if stripped else ""


def parse_session(path: Path) -> Session:
    session = Session(str(path), subagent="subagents" in path.parts)
    tool_names: dict[str, str] = {}
    explored = reads = 0
    edited = False
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not any(marker in line for marker in INTERESTING):
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            stamp = _timestamp(record.get("timestamp"))
            if stamp:
                session.start = stamp if session.start is None else min(session.start, stamp)
                session.end = stamp if session.end is None else max(session.end, stamp)
            if session.project is None and record.get("cwd"):
                session.project = record["cwd"]
            attachment = record.get("attachment")
            if isinstance(attachment, dict) and attachment.get("type") == "edited_text_file":
                session.changed_on_disk += 1
            message = record.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    name = str(block.get("name", "?"))
                    tool_names[str(block.get("id"))] = name
                    session.tool_calls[name] += 1
                    data = block.get("input") if isinstance(block.get("input"), dict) else {}
                    if name in EDIT_TOOLS and not edited:
                        edited = True
                        session.explore_before_edit, session.reads_before_edit = explored, reads
                    if not edited:
                        if name in EXPLORE_TOOLS:
                            explored += 1
                            reads += name == "Read"
                        elif name == "Bash" and _first_word(str(data.get("command", ""))) in EXPLORE_COMMANDS:
                            explored += 1
                    if name == "Skill" and data.get("skill"):
                        session.skills[str(data["skill"])] += 1
                    elif name in ("Agent", "Task"):
                        session.subagents[str(data.get("subagent_type") or "general-purpose")] += 1
                    elif name.startswith("mcp__"):
                        session.mcp_servers[name.split("__")[1]] += 1
                    elif name == "Bash":
                        command = str(data.get("command", ""))
                        for match in CTK_COMMAND.finditer(command):
                            if match.group(1) in COMMANDS:
                                session.ctk_commands[match.group(1)] += 1
                elif block.get("type") == "tool_result":
                    size = _result_length(block.get("content"))
                    session.result_chars += size
                    if block.get("is_error"):
                        session.tool_errors += 1
                    if tool_names.get(str(block.get("tool_use_id"))) == "Bash":
                        session.bash_output_chars.append(size)
    return session


def find_sessions(root: Path, since_days: float | None, include_subagents: bool) -> list[Path]:
    cutoff = time.time() - since_days * 86400 if since_days else None
    paths = list(root.glob("*/*.jsonl"))
    if include_subagents:
        paths += list(root.glob("*/*/subagents/*.jsonl"))
    return sorted(p for p in paths if cutoff is None or p.stat().st_mtime >= cutoff)


@dataclass
class Summary:
    sessions: int
    subagent_sessions: int
    tool_calls: int
    tool_errors: int
    error_rate: float
    median_explore_before_edit: float | None
    median_reads_before_edit: float | None
    bash_calls: int
    bash_output_avg_chars: float
    bash_output_max_chars: int
    tool_result_chars: int
    changed_on_disk_notices: int
    changed_on_disk_per_session: float
    top_tools: list[tuple[str, int]]
    skills: list[tuple[str, int]]
    subagents: list[tuple[str, int]]
    mcp_servers: list[tuple[str, int]]
    ctk_commands: list[tuple[str, int]]


def summarise(sessions: list[Session]) -> Summary:
    tools, skills, subagents, mcp, ctk = Counter(), Counter(), Counter(), Counter(), Counter()
    bash: list[int] = []
    for s in sessions:
        tools.update(s.tool_calls)
        skills.update(s.skills)
        subagents.update(s.subagents)
        mcp.update(s.mcp_servers)
        ctk.update(s.ctk_commands)
        bash.extend(s.bash_output_chars)
    main = [s for s in sessions if not s.subagent]
    explore = [s.explore_before_edit for s in main if s.explore_before_edit is not None]
    reads = [s.reads_before_edit for s in main if s.reads_before_edit is not None]
    calls = sum(tools.values())
    errors = sum(s.tool_errors for s in sessions)
    notices = sum(s.changed_on_disk for s in sessions)
    return Summary(
        sessions=len(main),
        subagent_sessions=len(sessions) - len(main),
        tool_calls=calls,
        tool_errors=errors,
        error_rate=round(errors / calls, 4) if calls else 0.0,
        median_explore_before_edit=statistics.median(explore) if explore else None,
        median_reads_before_edit=statistics.median(reads) if reads else None,
        bash_calls=len(bash),
        bash_output_avg_chars=round(statistics.fmean(bash), 1) if bash else 0.0,
        bash_output_max_chars=max(bash, default=0),
        tool_result_chars=sum(s.result_chars for s in sessions),
        changed_on_disk_notices=notices,
        changed_on_disk_per_session=round(notices / len(main), 2) if main else 0.0,
        top_tools=tools.most_common(10),
        skills=skills.most_common(),
        subagents=subagents.most_common(),
        mcp_servers=mcp.most_common(),
        ctk_commands=ctk.most_common(),
    )


def _pairs(items: list[tuple[str, int]]) -> str:
    return ", ".join(f"{name} {count}" for name, count in items) or "-"


def render(summary: Summary, label: str, style: Style | None = None) -> str:
    st = style or Style.detect()
    if st.enabled:
        return _render_styled(summary, label, st)

    def tokens(chars: float) -> str:
        return f"~{chars / 4:,.0f} tokens"

    rows = [
        ("sessions", f"{summary.sessions} (+{summary.subagent_sessions} subagent)"),
        ("tool calls", f"{summary.tool_calls:,} · errors {summary.tool_errors:,} ({summary.error_rate:.1%})"),
        ("explore calls before 1st edit (median)", str(summary.median_explore_before_edit)),
        ("Read calls before 1st edit (median)", str(summary.median_reads_before_edit)),
        (
            "Bash output",
            f"{summary.bash_calls:,} calls · avg {summary.bash_output_avg_chars:,.0f} chars "
            f"({tokens(summary.bash_output_avg_chars)}) · max {summary.bash_output_max_chars:,}",
        ),
        ("all tool results", f"{summary.tool_result_chars:,} chars ({tokens(summary.tool_result_chars)})"),
        (
            "'file changed on disk' notices",
            f"{summary.changed_on_disk_notices} ({summary.changed_on_disk_per_session} per session)",
        ),
        ("top tools", _pairs(summary.top_tools)),
        ("skills", _pairs(summary.skills)),
        ("subagents", _pairs(summary.subagents)),
        ("MCP servers", _pairs(summary.mcp_servers)),
        ("ctk commands", _pairs(summary.ctk_commands)),
    ]
    width = max(len(name) for name, _ in rows)
    return "\n".join([f"ctk sessions · {label}", *(f"{name:<{width}}  {value}" for name, value in rows)])


def _human(value: float) -> str:
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(value) >= size:
            return f"{value / size:.1f}{unit}"
    return f"{value:,.0f}"


def _render_styled(summary: Summary, label: str, st: Style) -> str:
    def row(name: str, value: str) -> str:
        return f"    {st.muted(name.ljust(18))}{value}"

    def section(title: str) -> str:
        return f"  {st.accent(title, bold=True)}"

    rate = summary.error_rate
    rate_text = f"{rate:.1%}"
    rate_colored = st.ok(rate_text) if rate < 0.02 else st.warn(rate_text) if rate < 0.05 else st.err(rate_text)
    notices = summary.changed_on_disk_per_session
    notice_text = f"{notices:g} / session"
    notice_colored = st.ok(notice_text) if notices < 2 else st.warn(notice_text) if notices < 6 else st.err(notice_text)
    avg_chars, all_chars = summary.bash_output_avg_chars, summary.tool_result_chars
    median_explore = "-" if summary.median_explore_before_edit is None else f"{summary.median_explore_before_edit:g}"
    median_reads = "-" if summary.median_reads_before_edit is None else f"{summary.median_reads_before_edit:g}"
    lines = [
        st.header("ctk sessions", label),
        "",
        section("Activity"),
        row("sessions", f"{st.bold(f'{summary.sessions:,}')} {st.muted(f'(+{summary.subagent_sessions} subagent)')}"),
        row(
            "tool calls",
            f"{st.bold(f'{summary.tool_calls:,}')} {st.muted('·')} {summary.tool_errors:,} errors ({rate_colored})",
        ),
        "",
        section("Context"),
        row(
            "Bash output",
            f"avg {st.bold(f'{avg_chars:,.0f}')} chars {st.muted(f'~{avg_chars / 4:,.0f} tokens')}"
            f" {st.muted('·')} max {summary.bash_output_max_chars:,}",
        ),
        row(
            "all tool results",
            f"{st.bold(_human(all_chars))} chars {st.muted(f'~{_human(all_chars / 4)} tokens')}",
        ),
        row("changed on disk", f"{st.bold(str(summary.changed_on_disk_notices))} ({notice_colored})"),
        "",
        section("Before the first edit (median)"),
        row("explore calls", st.bold(median_explore)),
        row("Read calls", st.bold(median_reads)),
        "",
        section("Top tools"),
    ]
    top = summary.top_tools
    peak = top[0][1] if top else 0
    name_w = max((len(name) for name, _ in top), default=0)
    for name, count in top:
        lines.append(f"    {name.ljust(name_w)}  {st.bar(count, peak, 26).ljust(26)} {st.muted(f'{count:,}')}")
    lines.append("")
    for title, items in (
        ("Skills", summary.skills),
        ("Subagents", summary.subagents),
        ("MCP servers", summary.mcp_servers),
        ("ctk", summary.ctk_commands),
    ):
        listed = st.muted(" · ").join(f"{st.accent2(name)} {st.muted(str(count))}" for name, count in items)
        lines.append(f"  {st.accent(title.ljust(12), bold=True)}{listed or st.muted('none')}")
    return "\n".join(lines)


def weekly_csv(sessions: list[Session]) -> str:
    """One row per ISO week, for before/after comparisons."""
    weeks: dict[str, list[Session]] = {}
    for s in sessions:
        if s.end is None:
            continue
        year, week, _ = datetime.fromtimestamp(s.end, UTC).isocalendar()
        weeks.setdefault(f"{year}-W{week:02d}", []).append(s)
    out = io.StringIO()
    fields = [
        "week",
        "sessions",
        "tool_calls",
        "error_rate",
        "median_explore_before_edit",
        "bash_output_avg_chars",
        "changed_on_disk_per_session",
    ]
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for week in sorted(weeks):
        summary = summarise(weeks[week])
        row = {key: value for key, value in asdict(summary).items() if key in fields}
        writer.writerow({"week": week, **row})
    return out.getvalue()
