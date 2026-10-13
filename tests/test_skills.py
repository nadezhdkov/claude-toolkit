import re
from pathlib import Path

import pytest

from claude_toolkit import COMMANDS, cli

SKILLS = Path(__file__).resolve().parents[1] / "plugin" / "skills"
NAMES = sorted(path.name for path in SKILLS.iterdir() if path.is_dir())


def frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---\n"), "frontmatter must open on the first line"
    block = text.split("---\n", 2)[1]
    return dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)


def test_the_skills_exist():
    assert NAMES == ["debug", "handoff", "onboard-repo", "orchestrate", "security-pass", "ship", "visual-qa"]


@pytest.mark.parametrize("name", NAMES)
def test_skill_is_well_formed_and_cheap_to_list(name):
    text = (SKILLS / name / "SKILL.md").read_text()
    meta = frontmatter(text)
    assert meta["name"] == name
    # The description is loaded into every session: keep it short (the hard limit is 1,536).
    assert 80 <= len(meta["description"]) <= 400
    assert len(text.splitlines()) < 200


@pytest.mark.parametrize("name", NAMES)
def test_skill_only_mentions_real_ctk_commands_and_skills(name):
    text = (SKILLS / name / "SKILL.md").read_text()
    for command in re.findall(r"`ctk ([a-z-]+)", text):
        assert command in COMMANDS, f"{name} mentions unknown `ctk {command}`"
    for kind in re.findall(r"`ctk shoot ([a-z-]+)", text):
        cli.build_parser().parse_args(["shoot", kind, "x"] if kind != "sheet" else ["shoot", "sheet", "x.png"])
    for other in re.findall(r"the `([a-z-]+)` skill", text):
        assert other in NAMES, f"{name} refers to a missing skill `{other}`"
