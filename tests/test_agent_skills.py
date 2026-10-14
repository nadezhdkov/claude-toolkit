import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sync_agent_skills", ROOT / "scripts" / "sync_agent_skills.py")
sync = importlib.util.module_from_spec(spec)
sys.modules["sync_agent_skills"] = sync
spec.loader.exec_module(sync)


def skill(root: Path, where: str, name: str, body: str = "body") -> Path:
    folder = root / where / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n{body}\n", encoding="utf-8")
    return folder


def test_the_mirror_of_this_repository_is_up_to_date():
    assert sync.differences(ROOT) == [], "run `make skills`"


def test_every_skill_of_the_repository_is_mirrored_except_the_claude_only_ones():
    mirrored = {p.parent.name for p in (ROOT / ".agents" / "skills").glob("*/SKILL.md")}
    sources = {p.parent.name for where in sync.SOURCES for p in (ROOT / where).glob("*/SKILL.md")}
    assert mirrored == sources - sync.CLAUDE_ONLY
    assert {"debug", "ship", "handoff", "issue"} <= mirrored and "orchestrate" not in mirrored


def test_mirrored_skills_are_valid_and_leave_claude_code_features_out():
    for path in (ROOT / ".agents" / "skills").glob("*/SKILL.md"):
        text = path.read_text(encoding="utf-8")
        assert text.startswith(f"---\nname: {path.parent.name}\ndescription: "), path
        assert "ctk:test-runner" not in text and "ctk:reviewer" not in text, f"{path}: needs Claude Code subagents"


def test_sync_copies_support_files_and_removes_stale_ones(tmp_path):
    one = skill(tmp_path, "plugin/skills", "one")
    (one / "refs").mkdir()
    (one / "refs" / "notes.md").write_text("n", encoding="utf-8")
    skill(tmp_path, ".claude/skills", "two")
    skill(tmp_path, "plugin/skills", "orchestrate")
    (tmp_path / ".agents/skills/gone").mkdir(parents=True)
    (tmp_path / ".agents/skills/gone/SKILL.md").write_text("old", encoding="utf-8")
    assert "stale gone/SKILL.md" in sync.differences(tmp_path)
    sync.write(tmp_path)
    base = tmp_path / ".agents" / "skills"
    assert sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()) == [
        "README.md",
        "one/SKILL.md",
        "one/refs/notes.md",
        "two/SKILL.md",
    ]
    assert sync.differences(tmp_path) == []
    (base / "two" / "SKILL.md").write_text("edited by hand", encoding="utf-8")
    assert sync.differences(tmp_path) == ["differs two/SKILL.md"]


def test_crlf_line_endings_of_a_windows_checkout_are_not_a_difference(tmp_path):
    skill(tmp_path, "plugin/skills", "one")
    sync.write(tmp_path)
    for path in (tmp_path / ".agents").rglob("*.md"):
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert sync.differences(tmp_path) == []


@pytest.mark.parametrize(("edit", "expected"), [(False, 0), (True, 1)])
def test_check_command(tmp_path, capsys, edit, expected):
    skill(tmp_path, "plugin/skills", "one")
    assert sync.main(["--root", str(tmp_path)]) == 0
    if edit:
        (tmp_path / ".agents/skills/one/SKILL.md").write_text("changed", encoding="utf-8")
    assert sync.main(["--root", str(tmp_path), "--check"]) == expected
    assert ("differs one/SKILL.md" in capsys.readouterr().out) == bool(expected)
