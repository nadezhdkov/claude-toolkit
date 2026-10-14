"""The relay-resume benchmark case, run without Claude: the scenario builds, the checks tell a finished
feature from an unfinished one and from one that broke the handoff's decisions, and the with arm gets the note."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from claude_toolkit import hooks

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "benchmark" / "cases" / "relay-resume"
pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("bash"), reason="the case runs in a Linux container"
)

FINISHED = {
    "invoices.py": '''
def _quote(value):
    if any(char in value for char in ',"\\n\\r'):
        return '"' + value.replace('"', '""') + '"'
    return value


def export_csv(invoices):
    """One row per invoice; fields with a comma, a quote or a line break are quoted."""
    rows = ["number,customer,total"]
    for invoice in invoices:
        fields = (invoice.number, invoice.customer, format_cents(invoice.total_cents()))
        rows.append(",".join(_quote(field) for field in fields))
    return "\\n".join(rows) + "\\n"
''',
}


def git(workspace, *args):
    return subprocess.run(["git", "-C", str(workspace), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def workspace(tmp_path):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_SYSTEM": os.devnull}
    work = tmp_path / "work"
    work.mkdir()
    done = subprocess.run(
        ["bash", str(CASE / "setup.sh")], cwd=work, env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    return work


def check(workspace, name):
    done = subprocess.run(
        ["bash", str(CASE / "checks" / f"{name}.sh")], cwd=workspace, capture_output=True, text=True, check=False
    )
    return done.returncode == 0, done.stdout


def finish(workspace, *, wire=True, export=None):
    """What a session that completed the feature would leave behind."""
    invoices = workspace / "invoices.py"
    text = invoices.read_text(encoding="utf-8")
    text = text[: text.index("def export_csv")].rstrip("\n") + "\n\n" + (export or FINISHED["invoices.py"])
    invoices.write_text(text, encoding="utf-8")
    if wire:
        cli = workspace / "cli.py"
        text = cli.read_text(encoding="utf-8")
        text = text.replace(
            "    if args.total:",
            '    if args.csv:\n        with open(args.csv, "w", encoding="utf-8", newline="") as handle:\n'
            "            handle.write(export_csv(invoices))\n        return 0\n    if args.total:",
        ).replace("import Invoice, Line, format_cents", "import Invoice, Line, export_csv, format_cents")
        cli.write_text(text, encoding="utf-8")


def test_the_scenario_is_a_feature_left_half_done(workspace):
    assert git(workspace, "branch", "--show-current").strip() == "feat/csv-export"
    assert git(workspace, "log", "--format=%s").splitlines() == [
        "feat: export invoices as CSV (header and rows)",
        "feat: invoices with money in integer cents",
    ]
    assert git(workspace, "status", "--porcelain").split() == ["M", "cli.py"], "one uncommitted edit"
    handoff = (workspace / ".claude" / "handoff" / "feat-csv-export.md").read_text(encoding="utf-8")
    assert "## Next" in handoff and "bare" in handoff and "Never use float" in handoff
    assert ".claude/handoff/" in (workspace / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    tests = subprocess.run(
        [sys.executable, "-m", "unittest"], cwd=workspace, capture_output=True, text=True, check=False
    )
    assert tests.returncode == 0 and "Ran 5 tests" in tests.stderr, tests.stderr  # the command the handoff names


def test_the_untouched_workspace_does_not_pass(workspace):
    assert check(workspace, "csv_quoting_and_flag")[0] is False
    assert check(workspace, "decisions_kept")[0] is False, "doing nothing must not count as keeping the decisions"
    assert check(workspace, "history_intact")[0] is True, "the earlier work is there, which is all this one asks"


def test_a_finished_feature_passes_every_check(workspace):
    finish(workspace)
    for name in ("csv_quoting_and_flag", "decisions_kept", "history_intact"):
        passed, output = check(workspace, name)
        assert passed, f"{name}: {output}"


def test_ignoring_the_decisions_in_the_handoff_is_caught(workspace):
    """The csv module's default writer ends lines with CRLF, and a float is easy to reach for."""
    sloppy = """
import csv
import io


def export_csv(invoices):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["number", "customer", "total"])
    for invoice in invoices:
        writer.writerow([invoice.number, invoice.customer, "%.2f" % (invoice.total_cents() / 100)])
    return out.getvalue()
"""
    finish(workspace, export=sloppy)
    assert check(workspace, "csv_quoting_and_flag")[0] is False, "CRLF breaks the exact output"
    passed, output = check(workspace, "decisions_kept")
    assert passed is False and "decisions" in output


def test_quoting_without_wiring_the_option_is_incomplete(workspace):
    finish(workspace, wire=False)
    assert check(workspace, "csv_quoting_and_flag")[0] is False


def test_rewriting_the_earlier_commits_is_caught(workspace):
    finish(workspace)
    git(workspace, "reset", "--soft", "HEAD~1")
    git(workspace, "-c", "user.name=x", "-c", "user.email=x@example.com", "commit", "-q", "-m", "squashed")
    assert check(workspace, "history_intact")[0] is False


def test_the_with_arm_is_handed_the_state_at_startup(workspace, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    meta = (CASE / "prompt.md").read_text(encoding="utf-8")
    assert 'env: { CTK_RELAY: "1" }' in meta, "the case starts the session the way `ctk relay` does"
    monkeypatch.setenv("CTK_RELAY", "1")
    event = json.dumps(
        {"hook_event_name": "SessionStart", "source": "startup", "session_id": "s", "cwd": str(workspace)}
    )
    note = json.loads(hooks.dispatch("continuity", event).stdout)["hookSpecificOutput"]["additionalContext"]
    for expected in (
        "handed over by ctk relay",
        "branch feat/csv-export",
        "1 uncommitted file(s)",
        "Quote fields",
        "bare",
    ):
        assert expected in note, expected
    monkeypatch.delenv("CTK_RELAY")
    assert hooks.dispatch("continuity", event).stdout == "", "a plain start (the without arm) gets nothing"
