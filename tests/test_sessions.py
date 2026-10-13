import json

from claude_toolkit import sessions


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
        tool_use(4, "Bash", command="cd x && ctk runq -- pytest; ctk doctor"),
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
