import json
import subprocess
import sys

import pytest

from claude_toolkit import cli, runq, verify

PASS = [sys.executable, "-c", "print('3 passed in 0.1s')"]
FAIL = [sys.executable, "-c", "import sys; print('1 failed, 2 passed in 0.1s'); sys.exit(1)"]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@e.st"], ["config", "user.name", "t"],
                 ["config", "commit.gpgsign", "false"]):  # fmt: skip
        subprocess.run(["git", "-C", str(root), *args], check=True)
    (root / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)
    monkeypatch.chdir(root)
    return root


def verdicts(root):
    _, statuses = verify.status(root)
    return {s.command: s.verdict for s in statuses}


def test_runq_records_and_the_state_decides_freshness(repo):
    assert runq.run(PASS) == 0
    command = verify.normalise(PASS)
    assert verdicts(repo) == {command: "pass"}
    (repo / "app.py").write_text("x = 2\n")
    assert verdicts(repo) == {command: "stale"}, "an edit makes the old result prove nothing"
    (repo / "app.py").write_text("x = 1\n")
    assert verdicts(repo) == {command: "pass"}, "the same code state is the same evidence"
    (repo / "new.py").write_text("")
    assert verdicts(repo) == {command: "stale"}, "untracked files are part of the state"


def test_failures_are_reported_with_summary_and_log(repo, capsys):
    runq.run(FAIL)
    capsys.readouterr()
    assert cli.main(["verify"]) == 1
    out = capsys.readouterr().out
    assert "✗ fail" in out and "1 failed, 2 passed" in out and "log: " in out


def test_configured_checks_that_never_ran_are_listed(repo, capsys):
    (repo / ".claude-toolkit.toml").write_text(f"[verify]\ncommands = [{json.dumps(verify.normalise(PASS))}]\n")
    assert cli.main(["verify"]) == 1
    assert "? never" in capsys.readouterr().out
    assert cli.main(["verify", "run"]) == 0
    out = capsys.readouterr().out
    assert "✓ pass" in out and "3 passed" in out


def test_detected_checks(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n[dependency-groups]\ndev = ['pytest']\n")
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("")
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest", "lint": "eslint ."}}))
    (tmp_path / "pnpm-lock.yaml").write_text("")
    (tmp_path / "go.mod").write_text("module x\n")
    assert verify.detected_checks(tmp_path) == [
        ".venv/bin/python -m pytest -q", ".venv/bin/python -m ruff check .",
        "pnpm run test", "pnpm run lint", "go vet ./...", "go test ./...",
    ]  # fmt: skip


def test_outside_git_nothing_is_recorded_and_verify_explains(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    assert verify.record(PASS, tmp_path, 0, "", 0.1) is None
    assert cli.main(["verify"]) == 1
    assert "not inside a git repository" in capsys.readouterr().err


def test_json(repo, capsys):
    runq.run(PASS)
    capsys.readouterr()
    cli.main(["verify", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["checks"][0]["verdict"] == "pass" and data["state"]["commit"]


def test_a_broken_config_is_reported(repo, capsys):
    (repo / ".claude-toolkit.toml").write_text("[verify\ncommands = [")
    cli.main(["verify"])
    assert "ignoring .claude-toolkit.toml" in capsys.readouterr().err
