"""``agent-contract`` (SubagentStop): hold the ctk subagents to their output contract.

Each agent file in ``plugin/agents/`` declares its contract in the frontmatter:

    ctk-contract: max-lines=40; verdicts=approve,changes-requested,blocked; evidence-for=changes-requested

When one of these subagents finishes, its final message must fit in
``max-lines``, end with ``VERDICT: <one of verdicts>``, and, for the verdicts
in ``evidence-for``, cite at least one ``path:line`` or URL. Otherwise the
subagent is sent back once with the list of problems; if the rewrite still
breaks the contract, the report goes through and the user is told.
Agents without a contract (other plugins, built-ins) are ignored.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .base import Event, Outcome

VERDICT = re.compile(r"^VERDICT:\s*([a-z-]+)\s*$")
# path:line, a URL, or a test id such as tests/test_api.py::test_login (a file with an extension, not std::io).
EVIDENCE = re.compile(r"(?:[\w./~-]+\.[A-Za-z0-9]+:\d+)|(?:https?://\S+)|(?:[\w./-]+\.[A-Za-z0-9]+::\w+)")


@dataclass(frozen=True)
class Contract:
    max_lines: int
    verdicts: tuple[str, ...]
    evidence_for: tuple[str, ...] = field(default_factory=tuple)


def parse_contract(text: str) -> Contract | None:
    """The contract from an agent file's ``ctk-contract:`` frontmatter line."""
    if not text.startswith("---"):
        return None
    frontmatter = text.split("---", 2)[1] if text.count("---") >= 2 else ""
    match = re.search(r"^ctk-contract:\s*(.+)$", frontmatter, re.MULTILINE)
    if not match:
        return None
    fields = {}
    for part in match.group(1).split(";"):
        key, _, value = part.strip().partition("=")
        fields[key.strip()] = value.strip()
    try:
        max_lines = int(fields["max-lines"])
        verdicts = tuple(v.strip() for v in fields["verdicts"].split(",") if v.strip())
    except (KeyError, ValueError):
        return None
    evidence = tuple(v.strip() for v in fields.get("evidence-for", "").split(",") if v.strip())
    return Contract(max_lines, verdicts, evidence)


def agents_dirs() -> list[Path]:
    """Where agent files live: the running plugin, then this checkout's plugin."""
    dirs = []
    root = os.environ.get("CTK_PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        dirs.append(Path(root) / "agents")
    dirs.append(Path(__file__).resolve().parents[3] / "plugin" / "agents")
    return dirs


def contract_for(agent_type: str) -> Contract | None:
    plugin, _, name = agent_type.rpartition(":")
    if plugin != "ctk" or not name:
        return None  # another plugin's agent, a user's own agent of the same name, or a built-in
    for directory in agents_dirs():
        path = directory / f"{name}.md"
        if path.is_file():
            return parse_contract(path.read_text())
    return None


def violations(message: str, contract: Contract) -> list[str]:
    lines = message.strip().splitlines()
    problems = []
    if len(lines) > contract.max_lines:
        problems.append(f"the report has {len(lines)} lines; the limit is {contract.max_lines}")
    last = lines[-1].strip() if lines else ""
    match = VERDICT.match(last)
    allowed = " | ".join(contract.verdicts)
    if not match:
        problems.append(f"the last line must be `VERDICT: <{allowed}>`")
    elif match.group(1) not in contract.verdicts:
        problems.append(f"`{match.group(1)}` is not a valid verdict; use one of: {allowed}")
    elif match.group(1) in contract.evidence_for and not EVIDENCE.search("\n".join(lines[:-1])):
        problems.append(f"a `{match.group(1)}` verdict needs evidence: cite at least one path:line or URL")
    return problems


def handle(event: Event) -> Outcome:
    if event.name != "SubagentStop":
        return Outcome()
    agent_type = str(event.data.get("agent_type") or "")
    contract = contract_for(agent_type)
    if contract is None:
        return Outcome()
    message = event.data.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        return Outcome()  # nothing to judge: fail open rather than send every agent back
    problems = violations(message, contract)
    if not problems:
        return Outcome()
    listing = "\n".join(f"- {problem}" for problem in problems)
    if event.data.get("stop_hook_active"):
        return Outcome.message(f"agent-contract: {agent_type} still breaks its output contract:\n{listing}")
    reason = (
        f"Your final report breaks the {agent_type} output contract:\n{listing}\n"
        "Rewrite only the final report so it follows the contract in your instructions; do not redo the work."
    )
    return Outcome.json({"decision": "block", "reason": reason})
