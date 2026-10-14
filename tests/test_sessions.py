import json
from datetime import UTC, datetime

import pytest

from claude_toolkit import cli, sessions


def tool_use(i, name, **data):
    return {
        "type": "assistant",
        "timestamp": f"2026-10-0{1 + i % 8}T10:00:00Z",
        "cwd": "/work/demo",
        "message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": data}]},
    }


def tool_result(i, text, error=False):
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": text, "is_error": error}]},
    }


def write_session(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def demo_session(tmp_path):
    records = [
        tool_use(0, "Read", file_path="/a"),
        tool_result(0, "x" * 10),
        tool_use(1, "Bash", command="grep -n foo src"),
        tool_result(1, "y" * 100),
        tool_use(2, "Grep", pattern="bar"),
        tool_result(2, "", error=True),
        tool_use(3, "Edit", file_path="/a"),
        tool_result(3, "ok"),
        {"type": "attachment", "attachment": {"type": "edited_text_file", "filename": "/a", "snippet": "secret"}},
        tool_use(4, "Bash", command="cd x && ctk runq -- pytest; ctk doctor; git commit -m 'ctk as a tool'"),
        tool_result(4, [{"type": "text", "text": "z" * 50}]),
        tool_use(5, "Skill", skill="debug"),
        tool_use(6, "Agent", subagent_type="Explore", prompt="private words"),
        tool_use(7, "mcp__game-assets__search_game_assets", query="maze"),
        "not json at all",
    ]
    path = tmp_path / "-work-demo" / "s1.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in records))
    return path


def test_parse_session_counts_without_copying_content(tmp_path):
    session = sessions.parse_session(demo_session(tmp_path))
    assert session.project == "/work/demo"
    assert session.explore_before_edit == 3 and session.reads_before_edit == 1
    assert session.tool_errors == 1
    assert session.bash_output_chars == [100, 50]
    assert session.changed_on_disk == 1
    assert session.skills == {"debug": 1}
    assert session.subagents == {"Explore": 1}
    assert session.mcp_servers == {"game-assets": 1}
    assert session.ctk_commands == {"runq": 1, "doctor": 1}
    rendered = sessions.render(sessions.summarise([session]), "test")
    assert "secret" not in rendered and "private words" not in rendered


def test_find_sessions_includes_subagents_on_request(tmp_path):
    demo_session(tmp_path)
    write_session(tmp_path / "-work-demo" / "s1" / "subagents" / "agent-1.jsonl", [tool_use(0, "Read")])
    assert len(sessions.find_sessions(tmp_path, None, include_subagents=False)) == 1
    found = sessions.find_sessions(tmp_path, None, include_subagents=True)
    summary = sessions.summarise([sessions.parse_session(p) for p in found])
    assert summary.sessions == 1 and summary.subagent_sessions == 1


def test_weekly_csv(tmp_path):
    session = sessions.parse_session(demo_session(tmp_path))
    rows = sessions.weekly_csv([session]).strip().splitlines()
    assert rows[0].startswith("week,sessions,tool_calls")
    assert rows[1].startswith("2026-W") and len(rows) >= 2


def model_call(message_id, fresh, written, read, out, *blocks):
    usage = {"input_tokens": fresh, "cache_creation_input_tokens": written, "cache_read_input_tokens": read,
             "output_tokens": out}  # fmt: skip
    return {"type": "assistant", "timestamp": "2026-10-05T10:00:00Z",
            "message": {"id": message_id, "content": list(blocks), "usage": usage}}  # fmt: skip


def test_tokens_peak_context_compactions_and_carried_results(tmp_path):
    read = {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": "/secret/plan.md"}}
    reread = {"type": "tool_use", "id": "r2", "name": "Read", "input": {"file_path": "/secret/plan.md"}}
    records = [
        model_call("m1", 5, 1000, 0, 10, read),
        model_call("m1", 5, 1000, 0, 10),  # the same call split over two records: counted once
        tool_result_for("r1", "a" * 400),
        model_call("m2", 1, 50, 1000, 20, reread),
        tool_result_for("r2", "b" * 100),
        model_call("m3", 1, 10, 1050, 30),
        {"type": "system", "subtype": "compact_boundary", "timestamp": "2026-10-05T10:01:00Z"},
        model_call("m4", 2, 300, 0, 5),
    ]
    path = tmp_path / "-work-demo" / "s2.jsonl"
    write_session(path, records)
    session = sessions.parse_session(path)
    assert session.model_calls == 4
    assert session.tokens["cache_read_input_tokens"] == 2050 and session.tokens["output_tokens"] == 65
    assert session.peak_context == 1061  # m3: 1 + 10 + 1050
    assert session.compactions == 1 and session.repeated_reads == 1
    # r1 (400 chars) is read again by m2 and m3; r2 (100) by m3; both are gone after the compaction.
    assert session.carried_chars_by_tool == {"Read": 400 * 2 + 100 * 1}
    summary = sessions.summarise([session])
    assert summary.context_tokens == 9 + 1360 + 2050 and summary.cache_hit_rate == round(2050 / 3419, 4)
    rendered = sessions.render(summary, "test")
    assert "plan.md" not in rendered and "/secret" not in rendered
    assert "repeated reads of a file" in rendered and "compactions" in rendered


def tool_result_for(tool_id, text):
    return {"type": "user", "timestamp": "2026-10-05T10:00:00Z",
            "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": text}]}}  # fmt: skip


# --- compare two periods -----------------------------------------------------------------------


def window_session(peak, bash_chars, end="2026-10-05T10:00:00Z", name="s"):
    """A session whose largest window is ``peak`` tokens and whose Bash output is read again once."""
    bash = {"type": "tool_use", "id": f"b-{name}", "name": "Bash", "input": {"command": "pytest"}}
    records = [
        {**model_call(f"{name}1", 0, 0, peak // 2, 1, bash), "timestamp": end},
        {**tool_result_for(f"b-{name}", "x" * bash_chars), "timestamp": end},
        {**model_call(f"{name}2", 0, 0, peak, 1), "timestamp": end},
    ]
    return records


def summary_of(tmp_path, label, peaks, bash_chars):
    paths = []
    for i, peak in enumerate(peaks):
        path = tmp_path / label / f"{label}{i}.jsonl"
        write_session(path, window_session(peak, bash_chars, name=f"{label}{i}"))
        paths.append(path)
    return sessions.summarise([sessions.parse_session(p) for p in paths])


def test_compare_passes_only_when_both_fall_by_half(tmp_path):
    base = summary_of(tmp_path, "a", [800_000] * 5, 40_000)
    assert base.median_bash_reread_tokens == 10_000, "10,000 tokens read again by the one later call"
    better = summary_of(tmp_path, "b", [300_000] * 5, 16_000)
    result = sessions.compare(base, better)
    assert result.verdict == "pass" and [m.met for m in result.metrics[:2]] == [True, True]
    assert result.metrics[0].change == -0.625 and result.metrics[2].met is None, "the others only inform"
    window_only = sessions.compare(base, summary_of(tmp_path, "c", [300_000] * 5, 40_000))
    assert window_only.verdict == "fail" and [m.met for m in window_only.metrics[:2]] == [True, False]
    assert sessions.compare(base, summary_of(tmp_path, "d", [500_000] * 5, 16_000)).verdict == "fail", (
        "-37% is not half"
    )
    assert sessions.compare(base, summary_of(tmp_path, "e", [400_000] * 5, 20_000)).verdict == "pass", (
        "exactly half counts"
    )


def test_compare_needs_enough_sessions_and_data(tmp_path):
    base = summary_of(tmp_path, "a", [800_000] * 5, 40_000)
    few = summary_of(tmp_path, "b", [100_000] * 4, 4_000)
    assert sessions.compare(base, few).verdict == "insufficient", "four sessions say nothing about a median"
    assert sessions.compare(base, sessions.summarise([])).verdict == "insufficient"
    assert sessions.compare(sessions.summarise([]), base).metrics[0].change is None


def test_period_parsing():
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC).timestamp()
    start, end = sessions.parse_period("2026-10-06..2026-10-13", now)
    assert end - start == 8 * 86400, "both days are included"
    assert datetime.fromtimestamp(start, UTC).isoformat() == "2026-10-06T00:00:00+00:00"
    assert sessions.parse_period("14d..7d", now) == (now - 14 * 86400, now - 7 * 86400)
    assert sessions.parse_period("2026-10-01..0d", now)[1] == now
    for bad in ("2026-10-06", "7d..14d", "2026-10-13..2026-10-06", "yesterday..today", "2026-02-30..2026-03-01"):
        with pytest.raises(ValueError):
            sessions.parse_period(bad, now)


def test_in_period_uses_the_end_of_each_session(tmp_path):
    inside = sessions.parse_session(
        write_and_return(tmp_path / "in.jsonl", window_session(10, 4, "2026-10-08T10:00:00Z", "i"))
    )
    outside = sessions.parse_session(
        write_and_return(tmp_path / "out.jsonl", window_session(10, 4, "2026-10-20T10:00:00Z", "o"))
    )
    nothing = sessions.Session("none")
    period = sessions.parse_period("2026-10-06..2026-10-13")
    assert sessions.in_period([inside, outside, nothing], period) == [inside]


def write_and_return(path, records):
    write_session(path, records)
    return path


def test_compare_command(tmp_path, capsys, monkeypatch):
    for i in range(5):
        write_session(
            tmp_path / "-p" / f"old{i}.jsonl", window_session(800_000, 40_000, "2026-10-02T10:00:00Z", f"o{i}")
        )
        write_session(
            tmp_path / "-p" / f"new{i}.jsonl", window_session(300_000, 16_000, "2026-10-09T10:00:00Z", f"n{i}")
        )
    args = ["sessions", "--root", str(tmp_path), "--compare", "2026-10-01..2026-10-03", "2026-10-08..2026-10-10"]
    monkeypatch.setenv("NO_COLOR", "1")
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "-62% ✓" in out and "median peak window (tokens)*" in out
    assert cli.main([*args, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "pass"
    assert (
        cli.main(["sessions", "--root", str(tmp_path), "--compare", "2026-10-08..2026-10-10", "2026-10-01..2026-10-03"])
        == 1
    )
    assert "FAIL" in capsys.readouterr().out
    assert cli.main(["sessions", "--root", str(tmp_path), "--compare", "nope", "7d..0d"]) == 2
    assert "not a period" in capsys.readouterr().err
