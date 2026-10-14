"""``ctk sessions``: usage metrics from Claude Code transcripts.

Reads ``~/.claude/projects/**.jsonl`` and reports counts only: tool calls,
tool errors, exploration before the first edit, command output sizes, real
token usage (fresh input, cache writes and reads, output) and the peak context
of each session, compactions, repeated reads of the same file, "file changed
on disk" notices and use of skills, subagents, MCP servers and ``ctk`` itself.
Message text and file names are never copied into the output.
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
INTERESTING = ('"tool_use"', '"tool_result"', '"edited_text_file"', '"timestamp"', '"usage"', "ompact")
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


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
    tokens: Counter = field(default_factory=Counter)  # USAGE_KEYS summed once per model call
    model_calls: int = 0
    peak_context: int = 0  # the most tokens one call read: how full the window got
    windows: list[int] = field(default_factory=list)  # tokens each model call read, in order
    first_edit_window: int | None = None  # the window when the first edit was made
    compactions: int = 0
    repeated_reads: int = 0
    result_chars_by_tool: Counter = field(default_factory=Counter)
    # A tool result stays in the context and is read again by every later model call until a
    # compaction: size x those calls is what it really cost.
    carried_chars_by_tool: Counter = field(default_factory=Counter)
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
    usage_seen: set[str] = set()
    read_paths: set[int] = set()  # hashes only: file names never leave this function
    results: list[tuple[str, int, int]] = []  # (tool, chars, model calls so far)
    compacted_at: list[int] = []
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
            if record.get("isCompactSummary") or record.get("subtype") == "compact_boundary":
                session.compactions += 1
                compacted_at.append(session.model_calls)
            message_usage = record.get("message", {}).get("usage") if isinstance(record.get("message"), dict) else None
            message_id = str(record.get("message", {}).get("id") or record.get("uuid") or "") if message_usage else ""
            if isinstance(message_usage, dict) and message_id not in usage_seen:
                usage_seen.add(message_id)  # one model call is split over several records
                counts = {key: int(message_usage.get(key) or 0) for key in USAGE_KEYS}
                session.tokens.update(counts)
                session.model_calls += 1
                context = (
                    counts["input_tokens"] + counts["cache_creation_input_tokens"] + counts["cache_read_input_tokens"]
                )
                session.peak_context = max(session.peak_context, context)
                session.windows.append(context)
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
                        session.first_edit_window = session.windows[-1] if session.windows else None
                    if not edited:
                        if name in EXPLORE_TOOLS:
                            explored += 1
                            reads += name == "Read"
                        elif name == "Bash" and _first_word(str(data.get("command", ""))) in EXPLORE_COMMANDS:
                            explored += 1
                    if name == "Read" and data.get("file_path"):
                        key = hash(str(data["file_path"]))
                        if key in read_paths:
                            session.repeated_reads += 1
                        read_paths.add(key)
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
                    tool = tool_names.get(str(block.get("tool_use_id")), "?")
                    session.result_chars_by_tool[tool] += size
                    results.append((tool, size, session.model_calls))
                    if block.get("is_error"):
                        session.tool_errors += 1
                    if tool_names.get(str(block.get("tool_use_id"))) == "Bash":
                        session.bash_output_chars.append(size)
    for tool, size, at in results:
        until = next((point for point in compacted_at if point > at), session.model_calls)
        session.carried_chars_by_tool[tool] += size * max(0, until - at)
    return session


# --- Relay point ---------------------------------------------------------------
#
# Every model call reads the whole window again (from the cache), so a long
# session pays for its early tool results on every later call. Starting a fresh
# session (a relay) resets the window to what a new session needs to resume the
# work, at the price of writing that new prefix to the cache and of one extra
# turn to write the handoff. The model replays each real session as if it had
# relayed whenever its window passed a threshold, in cache-read equivalents.

CACHE_WRITE_WEIGHT = 12.5  # a cache write costs 12.5x a cache read (1.25 vs 0.1 of the input price)
HANDOFF_TOKENS = 4_000  # the brief the new session starts from
RELAY_TURNS = 2  # calls spent on writing the handoff and running `ctk relay`
RELAY_THRESHOLDS = tuple(range(100_000, 950_000, 50_000))
MIN_SAVING = 0.05  # below this a relay is not worth the lost thread


@dataclass
class RelayPoint:
    threshold: int | None  # None: no threshold saves at least MIN_SAVING
    saving: float  # fraction of the context cost saved at that threshold
    restart_window: int  # what a fresh session reads once it has resumed the work
    sessions: int  # sessions long enough to have relayed at the threshold
    relays: int


def restart_window(sessions: list[Session]) -> int:
    """Median window of a fresh session once it is ready to work: start plus exploration, plus the brief."""
    starts = [s.windows[0] for s in sessions if s.windows]
    ready = [s.first_edit_window for s in sessions if s.first_edit_window]
    base = statistics.median(ready) if ready else statistics.median(starts) if starts else 0
    return int(base) + HANDOFF_TOKENS


def replay(windows: list[int], threshold: int, restart: int) -> tuple[float, int]:
    """Context cost of a session that relays whenever its window reaches ``threshold``; and how many relays."""
    cost = 0.0
    relays = 0
    offset = 0  # tokens the relays have dropped from the window
    for window in windows:
        current = max(restart, window - offset) if offset else window
        if current >= threshold:
            cost += RELAY_TURNS * current + CACHE_WRITE_WEIGHT * restart
            offset = window - restart
            relays += 1
            current = restart
        cost += current
    return cost, relays


def relay_point(sessions: list[Session]) -> RelayPoint:
    """The highest threshold that keeps at least 90% of the best saving: fewer relays, nearly the same gain.

    Every relay costs some of the thread, which the model cannot price, so among
    thresholds that save about the same the one that interrupts least wins.
    """
    main = [s for s in sessions if not s.subagent and s.windows]
    restart = restart_window(main)
    actual = sum(sum(s.windows) for s in main)
    if not actual:
        return RelayPoint(None, 0.0, restart, 0, 0)
    points = []
    for threshold in RELAY_THRESHOLDS:
        if threshold < restart * 2:  # a fresh session would be half full already
            continue
        total, relays, touched = 0.0, 0, 0
        for s in main:
            cost, count = replay(s.windows, threshold, restart)
            total += cost
            relays += count
            touched += count > 0
        points.append(RelayPoint(threshold, round(1 - total / actual, 4), restart, touched, relays))
    best = max((p.saving for p in points), default=0.0)
    if best < MIN_SAVING:
        return RelayPoint(None, max(best, 0.0), restart, 0, 0)
    return max((p for p in points if p.saving >= best * 0.9), key=lambda p: p.threshold or 0)


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
    model_calls: int
    fresh_input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    context_tokens: int
    cache_hit_rate: float
    context_tokens_per_session: float
    median_peak_context: float | None
    max_peak_context: int
    compactions: int
    sessions_with_compaction: int
    repeated_reads: int
    repeated_reads_per_session: float
    median_window_growth: float | None  # tokens the window grows per model call
    median_bash_reread_tokens: float | None  # per session: shell output tokens read again by later calls
    relay_threshold: int | None
    relay_saving: float
    relay_restart_window: int
    relay_sessions: int
    result_chars_by_tool: list[tuple[str, int]]
    carried_chars_by_tool: list[tuple[str, int]]
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
    tokens: Counter = Counter()
    by_tool: Counter = Counter()
    carried: Counter = Counter()
    for s in sessions:
        tokens.update(s.tokens)
        by_tool.update(s.result_chars_by_tool)
        carried.update(s.carried_chars_by_tool)
    read_tokens = tokens["input_tokens"] + tokens["cache_creation_input_tokens"] + tokens["cache_read_input_tokens"]
    peaks = [s.peak_context for s in main if s.peak_context]
    repeated = sum(s.repeated_reads for s in main)
    growth = [(max(s.windows) - s.windows[0]) / (len(s.windows) - 1) for s in main if len(s.windows) > 1]
    relay = relay_point(main)
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
        model_calls=sum(s.model_calls for s in sessions),
        fresh_input_tokens=tokens["input_tokens"],
        cache_write_tokens=tokens["cache_creation_input_tokens"],
        cache_read_tokens=tokens["cache_read_input_tokens"],
        output_tokens=tokens["output_tokens"],
        context_tokens=read_tokens,
        cache_hit_rate=round(tokens["cache_read_input_tokens"] / read_tokens, 4) if read_tokens else 0.0,
        context_tokens_per_session=round(sum(sum(s.tokens[k] for k in USAGE_KEYS[:3]) for s in main) / len(main), 1)
        if main
        else 0.0,
        median_peak_context=statistics.median(peaks) if peaks else None,
        max_peak_context=max(peaks, default=0),
        compactions=sum(s.compactions for s in main),
        sessions_with_compaction=sum(1 for s in main if s.compactions),
        repeated_reads=repeated,
        repeated_reads_per_session=round(repeated / len(main), 2) if main else 0.0,
        median_window_growth=round(statistics.median(growth), 1) if growth else None,
        median_bash_reread_tokens=statistics.median(s.carried_chars_by_tool["Bash"] / 4 for s in main)
        if main
        else None,
        relay_threshold=relay.threshold,
        relay_saving=relay.saving,
        relay_restart_window=relay.restart_window,
        relay_sessions=relay.sessions,
        result_chars_by_tool=by_tool.most_common(5),
        carried_chars_by_tool=carried.most_common(5),
        top_tools=tools.most_common(10),
        skills=skills.most_common(),
        subagents=subagents.most_common(),
        mcp_servers=mcp.most_common(),
        ctk_commands=ctk.most_common(),
    )


def _peak(value: float | None) -> str:
    return "-" if value is None else f"{value:,.0f}"


def _relay(summary: Summary) -> str:
    if summary.relay_threshold is None:
        return f"none: a fresh session would save under {MIN_SAVING:.0%} of the context cost"
    return (
        f"{summary.relay_threshold:,} tokens · saves ~{summary.relay_saving:.0%} of the context cost"
        f" · {summary.relay_sessions} session(s) would relay · a fresh session resumes at"
        f" ~{summary.relay_restart_window:,}"
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
            "largest tool results",
            ", ".join(f"{name} {tokens(chars)}" for name, chars in summary.result_chars_by_tool) or "-",
        ),
        (
            "results re-read later",
            ", ".join(f"{name} {tokens(chars)}" for name, chars in summary.carried_chars_by_tool) or "-",
        ),
        (
            "tokens read (context)",
            f"{summary.context_tokens:,} · fresh {summary.fresh_input_tokens:,}"
            f" · cache write {summary.cache_write_tokens:,} · cache read {summary.cache_read_tokens:,}"
            f" ({summary.cache_hit_rate:.0%} cached)",
        ),
        ("tokens written", f"{summary.output_tokens:,} in {summary.model_calls:,} model calls"),
        (
            "context per session",
            f"avg {summary.context_tokens_per_session:,.0f} tokens read · peak window median "
            f"{_peak(summary.median_peak_context)} · max {summary.max_peak_context:,}",
        ),
        ("window growth per call (median)", _peak(summary.median_window_growth)),
        ("relay point", _relay(summary)),
        ("compactions", f"{summary.compactions} in {summary.sessions_with_compaction} session(s)"),
        ("repeated reads of a file", f"{summary.repeated_reads} ({summary.repeated_reads_per_session} per session)"),
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
        row(
            "repeated reads",
            f"{st.bold(str(summary.repeated_reads))} {st.muted(f'({summary.repeated_reads_per_session:g} / session)')}",
        ),
        "",
        section("Tokens (from usage records)"),
        row(
            "read",
            f"{st.bold(_human(summary.context_tokens))} {st.muted('·')} "
            f"{st.ok(f'{summary.cache_hit_rate:.0%} cached')} "
            + st.muted(
                f"(fresh {_human(summary.fresh_input_tokens)}, cache write {_human(summary.cache_write_tokens)})"
            ),
        ),
        row("written", f"{st.bold(_human(summary.output_tokens))} {st.muted(f'in {summary.model_calls:,} calls')}"),
        row(
            "per session",
            f"avg {st.bold(_human(summary.context_tokens_per_session))} read {st.muted('·')} peak window median "
            f"{st.bold(_peak(summary.median_peak_context))} {st.muted(f'max {summary.max_peak_context:,}')}",
        ),
        row("window growth", f"{st.bold(_peak(summary.median_window_growth))} {st.muted('tokens / call (median)')}"),
        row(
            "relay point",
            st.muted("none")
            if summary.relay_threshold is None
            else f"{st.bold(f'{summary.relay_threshold:,}')} {st.muted('·')} "
            f"{st.ok(f'saves ~{summary.relay_saving:.0%}')} "
            + st.muted(
                f"({summary.relay_sessions} sessions would relay, fresh one at ~{_human(summary.relay_restart_window)})"
            ),
        ),
        row(
            "compactions",
            f"{st.bold(str(summary.compactions))} {st.muted(f'in {summary.sessions_with_compaction} sessions')}",
        ),
        row(
            "carried results",
            st.muted(" · ").join(
                f"{st.accent2(name)} ~{_human(chars / 4)} tok" for name, chars in summary.carried_chars_by_tool
            )
            or st.muted("none"),
        ),
        row(
            "largest results",
            st.muted(" · ").join(
                f"{st.accent2(name)} ~{_human(chars / 4)} tok" for name, chars in summary.result_chars_by_tool
            )
            or st.muted("none"),
        ),
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
        "context_tokens_per_session",
        "cache_hit_rate",
        "median_peak_context",
        "compactions",
        "repeated_reads_per_session",
    ]
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for week in sorted(weeks):
        summary = summarise(weeks[week])
        row = {key: value for key, value in asdict(summary).items() if key in fields}
        writer.writerow({"week": week, **row})
    return out.getvalue()


# --- Comparing two periods ---------------------------------------------------------------------
#
# Phase 8 is done when, over a week of real use, the median peak window and the Bash re-read cost
# have both fallen by at least half. `--compare` states that as a verdict instead of two reports
# read side by side.

TARGET_DROP = 0.5
MIN_SESSIONS = 5  # fewer sessions in a period say nothing about a median


@dataclass
class Metric:
    name: str
    baseline: float | None
    current: float | None
    change: float | None  # (current - baseline) / baseline
    required: bool  # part of the Phase 8 criterion
    met: bool | None  # fell by at least TARGET_DROP; None when it is only informative or has no data


@dataclass
class Comparison:
    baseline: str
    current: str
    baseline_sessions: int
    current_sessions: int
    metrics: list[Metric]
    verdict: str  # pass | fail | insufficient


def _bound(text: str, now: float, end: bool) -> float:
    """``Nd`` is N days ago; ``YYYY-MM-DD`` is that day in UTC (its end, for the end of a period)."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)d", text)
    if match:
        return now - float(match.group(1)) * 86400
    try:
        day = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        raise ValueError(f"not a date or a number of days ago: {text!r} (use 2026-10-13 or 7d)") from None
    return day.timestamp() + (86400 if end else 0)


def parse_period(text: str, now: float | None = None) -> tuple[float, float]:
    """``START..END`` as two epoch times; both ends are dates (END inclusive) or ``Nd`` days ago."""
    now = time.time() if now is None else now
    start, sep, end = text.partition("..")
    if not sep:
        raise ValueError(f"not a period: {text!r} (use START..END, for example 2026-10-06..2026-10-13 or 14d..7d)")
    low, high = _bound(start, now, end=False), _bound(end, now, end=True)
    if low >= high:
        raise ValueError(f"the period {text!r} ends before it starts")
    return low, high


def in_period(sessions: list[Session], period: tuple[float, float]) -> list[Session]:
    """Sessions that ended in the period (a subagent follows its own timestamps)."""
    return [s for s in sessions if s.end is not None and period[0] <= s.end < period[1]]


def _metric(name: str, base: float | None, cur: float | None, required: bool) -> Metric:
    change = (cur - base) / base if base and cur is not None else None
    met = change is not None and change <= -TARGET_DROP if required else None
    return Metric(name, base, cur, change, required, met)


def compare(baseline: Summary, current: Summary, labels: tuple[str, str] = ("baseline", "current")) -> Comparison:
    metrics = [
        _metric("median peak window (tokens)", baseline.median_peak_context, current.median_peak_context, True),
        _metric(
            "Bash re-read per session (tokens, median)",
            baseline.median_bash_reread_tokens,
            current.median_bash_reread_tokens,
            True,
        ),
        _metric(
            "context read per session (tokens)",
            baseline.context_tokens_per_session,
            current.context_tokens_per_session,
            False,
        ),
        _metric(
            "compactions per session",
            baseline.compactions / baseline.sessions if baseline.sessions else None,
            current.compactions / current.sessions if current.sessions else None,
            False,
        ),
    ]
    required = [m for m in metrics if m.required]
    if min(baseline.sessions, current.sessions) < MIN_SESSIONS or any(m.change is None for m in required):
        verdict = "insufficient"
    else:
        verdict = "pass" if all(m.met for m in required) else "fail"
    return Comparison(labels[0], labels[1], baseline.sessions, current.sessions, metrics, verdict)


def _number(value: float | None) -> str:
    return "-" if value is None else f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.2f}"


def render_comparison(result: Comparison, style: Style | None = None) -> str:
    st = style or Style.detect()
    rows = []
    for m in result.metrics:
        change = "-" if m.change is None else f"{m.change:+.0%}"
        if m.required and m.change is not None:
            change = st.ok(change) if m.met else st.err(change)
        mark = "" if not m.required else (" ✓" if m.met else " ✗" if m.met is False else " ?")
        rows.append((m.name + ("*" if m.required else ""), _number(m.baseline), _number(m.current), change + mark))
    widths = [max(len(r[i]) for r in [("metric", "baseline", "current", "change"), *rows]) for i in range(3)]
    lines = [
        st.header("ctk sessions", f"{result.baseline} → {result.current}"),
        f"  {'metric'.ljust(widths[0])}  {'baseline'.rjust(widths[1])}  {'current'.rjust(widths[2])}  change",
        *(f"  {r[0].ljust(widths[0])}  {r[1].rjust(widths[1])}  {r[2].rjust(widths[2])}  {r[3]}" for r in rows),
        f"  sessions: {result.baseline_sessions} → {result.current_sessions}"
        f" (* part of the Phase 8 criterion: both must fall by {TARGET_DROP:.0%})",
    ]
    verdict = {
        "pass": st.ok("PASS: both fell by at least half", bold=True),
        "fail": st.err("FAIL: the criterion is not met", bold=True),
        "insufficient": st.warn(
            f"INSUFFICIENT DATA: need at least {MIN_SESSIONS} sessions in each period and data for both metrics",
            bold=True,
        ),
    }[result.verdict]
    return "\n".join([*lines, verdict, "  benchmark scores: not checked here; run benchmark/run.py and compare"])
