import pytest

from claude_toolkit import cli, setup
from claude_toolkit.common import EXIT_NEEDS_CONFIRMATION


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A home with no agents, an empty ~/.claude and no tools to install."""
    monkeypatch.setattr(setup, "claude_home", lambda: tmp_path / "claude")
    monkeypatch.setattr(setup, "agent_home", lambda: tmp_path / "home")
    monkeypatch.setattr(setup, "TOOLKIT_DEPENDENCIES", ())
    monkeypatch.setattr(setup, "claude_cli", lambda: None)
    (tmp_path / "home").mkdir()
    (tmp_path / "claude").mkdir()
    (tmp_path / "claude" / "CLAUDE.md").write_text(setup.with_snippet(""), encoding="utf-8")  # Claude Code is done
    return tmp_path


@pytest.fixture
def source(tmp_path, monkeypatch):
    folder = tmp_path / "src-skills"
    for name in ("debug", "ship", "issue"):
        (folder / name).mkdir(parents=True)
        (folder / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\nbody\n", encoding="utf-8")
    (folder / "ship" / "notes.md").write_text("support file", encoding="utf-8")
    (folder / "README.md").write_text("not a skill", encoding="utf-8")
    monkeypatch.setattr(setup, "skills_source", lambda: folder)
    return folder


def installed(machine) -> list[str]:
    root = machine / "home" / ".agents" / "skills"
    return sorted(p.name for p in root.iterdir()) if root.is_dir() else []


def test_nothing_is_offered_when_no_other_agent_is_found(machine, source, capsys):
    assert setup.other_agents() == []
    assert setup.agent_skill_steps() == []
    assert setup.run(assume_yes=True, dry_run=False, uninstall=False) == 0
    assert "nothing to do" in capsys.readouterr().out and installed(machine) == []


@pytest.mark.parametrize(
    ("folder", "name"), [(".codex", "Codex"), (".gemini", "Gemini CLI"), (".config/opencode", "opencode")]
)
def test_a_found_agent_makes_setup_offer_the_skills(machine, source, folder, name):
    (machine / "home" / folder).mkdir(parents=True)
    assert setup.other_agents() == [name]
    (step,) = setup.agent_skill_steps()
    assert "debug, ship" in step.description and "issue" not in step.description and name in step.description


def test_agents_flag_offers_without_a_detected_agent(machine, source):
    assert setup.agent_skill_steps() == [] and len(setup.agent_skill_steps(offer=True)) == 1


def test_skills_are_copied_marked_and_the_project_only_one_is_left_out(machine, source):
    assert setup.run(assume_yes=True, dry_run=False, uninstall=False, agents=True) == 0
    assert installed(machine) == ["debug", "ship"], "no issue skill, no README"
    ship = machine / "home" / ".agents" / "skills" / "ship"
    assert (ship / "notes.md").read_text() == "support file" and (ship / setup.SKILL_MARK).is_file()
    assert setup.agent_skill_steps(offer=True) == [], "a second run has nothing to do"


def test_a_changed_skill_is_updated_but_a_foreign_one_is_never_touched(machine, source):
    mine = machine / "home" / ".agents" / "skills"
    (mine / "ship").mkdir(parents=True)
    (mine / "ship" / "SKILL.md").write_text("my own ship skill", encoding="utf-8")
    (step,) = setup.agent_skill_steps(offer=True)
    assert "your own ship stay untouched" in step.description
    step.apply()
    assert (mine / "ship" / "SKILL.md").read_text() == "my own ship skill", "not overwritten"
    assert not (mine / "ship" / setup.SKILL_MARK).exists()
    (source / "debug" / "SKILL.md").write_text("---\nname: debug\ndescription: newer\n---\n", encoding="utf-8")
    (update,) = setup.agent_skill_steps(offer=True)
    assert "debug" in update.description and "ship" not in update.description.split("to")[0]
    update.apply()
    assert "newer" in (mine / "debug" / "SKILL.md").read_text() and (mine / "debug" / setup.SKILL_MARK).is_file()


def test_uninstall_removes_only_what_setup_copied(machine, source):
    mine = machine / "home" / ".agents" / "skills"
    (mine / "mine").mkdir(parents=True)
    (mine / "mine" / "SKILL.md").write_text("keep", encoding="utf-8")
    setup.run(assume_yes=True, dry_run=False, uninstall=False, agents=True)
    assert installed(machine) == ["debug", "mine", "ship"]
    assert setup.run(assume_yes=True, dry_run=False, uninstall=True) == 0
    assert installed(machine) == ["mine"]


def test_the_section_goes_only_into_the_files_named_and_without_the_hooks_sentence(machine, source):
    codex = machine / "home" / ".codex" / "AGENTS.md"
    codex.parent.mkdir(parents=True)
    codex.write_text("# My rules\n", encoding="utf-8")
    other = machine / "home" / ".gemini" / "GEMINI.md"
    setup.run(assume_yes=True, dry_run=False, uninstall=False, agents_files=[codex, other])
    assert "hook" in (machine / "claude" / "CLAUDE.md").read_text(encoding="utf-8"), (
        "Claude Code keeps its hooks sentence"
    )
    text = codex.read_text(encoding="utf-8")
    assert text.startswith("# My rules\n") and setup.START in text and "`ctk runq" in text
    assert "hook" not in text, "other agents do not have the plugin's hooks"
    assert "exit 3" in text and other.exists(), "a file that does not exist yet is created"
    backups = list(codex.parent.glob("AGENTS.md.claude-toolkit-backup-*"))
    assert len(backups) == 1 and backups[0].read_text() == "# My rules\n"
    assert setup.instruction_steps([codex, other]) == [], "idempotent"
    setup.run(assume_yes=True, dry_run=False, uninstall=True, agents_files=[codex])
    assert codex.read_text(encoding="utf-8") == "# My rules\n"
    assert setup.START in other.read_text(encoding="utf-8"), "only the files named are touched"


def test_the_agents_section_stays_small():
    assert len(setup.AGENTS_SNIPPET) < len(setup.SNIPPET) < 1200
    assert setup.SNIPPET.startswith(setup.START) and setup.AGENTS_SNIPPET.endswith(setup.END + "\n")


def test_dry_run_and_the_missing_terminal_change_nothing(machine, source, monkeypatch, capsys):
    file = machine / "AGENTS.md"
    assert setup.run(assume_yes=False, dry_run=True, uninstall=False, agents=True, agents_files=[file]) == 0
    assert installed(machine) == [] and not file.exists()
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["setup", "--agents", "--agents-file", str(file)]) == EXIT_NEEDS_CONFIRMATION
    assert installed(machine) == [] and not file.exists()
    assert "rerun with --yes" in capsys.readouterr().err


def test_command_line_flags(machine, source):
    file = machine / "g" / "AGENTS.md"
    assert cli.main(["setup", "--yes", "--agents", "--agents-file", str(file)]) == 0
    assert installed(machine) == ["debug", "ship"] and setup.START in file.read_text(encoding="utf-8")
    assert cli.main(["setup", "--yes", "--uninstall", "--agents-file", str(file)]) == 0
    assert installed(machine) == [] and setup.START not in file.read_text(encoding="utf-8")


def test_this_repository_provides_the_skills_setup_copies():
    real = setup.skills_source()
    assert real is not None and (real / "debug" / "SKILL.md").is_file()
    names = {d.name for d in real.iterdir() if (d / "SKILL.md").is_file()}
    assert names >= setup.PROJECT_ONLY, "PROJECT_ONLY names skills that exist"
    assert names - setup.PROJECT_ONLY >= {"debug", "ship", "handoff", "onboard-repo", "visual-qa", "security-pass"}
    assert "orchestrate" not in names


def test_the_messages_use_the_right_past_tense(machine, source, capsys):
    claude_md = machine / "claude" / "CLAUDE.md"
    claude_md.write_text("# mine\n", encoding="utf-8")
    file = machine / "AGENTS.md"
    file.write_text("# mine\n", encoding="utf-8")
    setup.run(assume_yes=True, dry_run=False, uninstall=False, agents_files=[file])
    out = capsys.readouterr().out
    assert "added the claude-toolkit section in" in out and "addd" not in out
    setup.AGENTS_SNIPPET += "<!-- newer -->\n"
    try:
        (step,) = setup.instruction_steps([file])
    finally:
        setup.AGENTS_SNIPPET = setup.AGENTS_SNIPPET.removesuffix("<!-- newer -->\n")
    assert step.description.startswith("update ") and step.apply().startswith("updated the claude-toolkit section")
