import json
import re
from pathlib import Path

import pytest

from claude_toolkit import COMMANDS, hooks
from claude_toolkit.hooks import agent_contract

AGENTS = Path(__file__).resolve().parents[1] / "plugin" / "agents"
NAMES = sorted(path.stem for path in AGENTS.glob("*.md"))


def frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---\n")
    return dict(line.split(": ", 1) for line in text.split("---\n", 2)[1].splitlines() if ": " in line)


def test_the_phase_6_agents_exist():
    assert NAMES == ["researcher", "reviewer", "test-runner"]


@pytest.mark.parametrize("name", NAMES)
def test_agent_is_read_only_cheap_to_list_and_has_a_contract(name):
    text = (AGENTS / f"{name}.md").read_text()
    meta = frontmatter(text)
    assert meta["name"] == name and 80 <= len(meta["description"]) <= 200
    denied = {tool.strip() for tool in meta["disallowedTools"].split(",")}
    assert {"Edit", "Write", "NotebookEdit", "Agent"} <= denied, "agents report; they never edit or spawn"
    contract = agent_contract.parse_contract(text)
    assert contract is not None and contract.max_lines <= 40
    # The body documents exactly the verdicts the hook enforces.
    for verdict in contract.verdicts:
        assert f"VERDICT: {verdict}" in text
    assert set(contract.evidence_for) <= set(contract.verdicts)
    for command in re.findall(r"`ctk ([a-z-]+)", text):
        assert command in COMMANDS


# --- contract checks ------------------------------------------------------------------

REVIEW = agent_contract.Contract(40, ("approve", "changes-requested", "blocked"), ("changes-requested",))


def test_a_report_that_follows_the_contract_passes():
    report = "[high] crash on empty input\n  where: src/app.py:12\nChecked the rest.\nVERDICT: changes-requested"
    assert agent_contract.violations(report, REVIEW) == []
    assert agent_contract.violations("Nothing to fix.\nVERDICT: approve", REVIEW) == []


@pytest.mark.parametrize(
    ("report", "problem"),
    [
        ("Looks fine to me.", "last line must be `VERDICT"),
        ("ok\nVERDICT: lgtm", "not a valid verdict"),
        ("there is a bug somewhere\nVERDICT: changes-requested", "needs evidence"),
        ("\n".join(["line"] * 45) + "\nVERDICT: approve", "limit is 40"),
    ],
)
def test_broken_reports_are_explained(report, problem):
    assert any(problem in found for found in agent_contract.violations(report, REVIEW))


def test_evidence_accepts_paths_urls_and_test_ids():
    for evidence in ("auth.py:41", "https://docs.example.com/x", "tests/test_api.py::test_login"):
        assert agent_contract.violations(f"see {evidence}\nVERDICT: changes-requested", REVIEW) == []


# --- the hook ----------------------------------------------------------------------------


def stop(agent_type: str, message: str, active: bool = False) -> str:
    return json.dumps({
        "hook_event_name": "SubagentStop", "session_id": "s", "cwd": "/tmp", "agent_type": agent_type,
        "last_assistant_message": message, "stop_hook_active": active,
    })  # fmt: skip


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CTK_PLUGIN_ROOT", str(AGENTS.parent))


def test_hook_sends_a_broken_report_back_once():
    first = json.loads(hooks.dispatch("agent-contract", stop("ctk:test-runner", "All good!")).stdout)
    assert first["decision"] == "block" and "VERDICT: <pass | fail | error>" in first["reason"]
    again = json.loads(hooks.dispatch("agent-contract", stop("ctk:test-runner", "All good!", active=True)).stdout)
    assert "decision" not in again and "still breaks" in again["systemMessage"]


def test_hook_lets_good_reports_and_other_agents_through():
    good = "Command: pytest\nResult: 3 passed\nVERDICT: pass"
    assert hooks.dispatch("agent-contract", stop("ctk:test-runner", good)).stdout == ""
    assert hooks.dispatch("agent-contract", stop("Explore", "whatever")).stdout == ""
    assert hooks.dispatch("agent-contract", stop("other-plugin:reviewer", "whatever")).stdout == ""


def test_contract_found_without_the_plugin_root(monkeypatch):
    monkeypatch.delenv("CTK_PLUGIN_ROOT")
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    assert agent_contract.contract_for("ctk:reviewer") == REVIEW


def test_missing_report_fails_open():
    event = json.loads(stop("ctk:reviewer", ""))
    del event["last_assistant_message"]
    assert hooks.dispatch("agent-contract", json.dumps(event)).stdout == ""


def test_a_users_own_agent_with_the_same_name_is_not_judged():
    assert agent_contract.contract_for("reviewer") is None
    assert hooks.dispatch("agent-contract", stop("reviewer", "no verdict here")).stdout == ""


def test_rust_paths_are_not_evidence():
    problems = agent_contract.violations("uses std::io wrongly\nVERDICT: changes-requested", REVIEW)
    assert any("needs evidence" in problem for problem in problems)


def test_files_without_extension_are_evidence_but_times_are_not():
    assert agent_contract.violations("see Makefile:12\nVERDICT: changes-requested", REVIEW) == []
    assert agent_contract.violations("ran at 12:30\nVERDICT: changes-requested", REVIEW) != []
