import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import posix_only

from claude_toolkit import __version__, cli, hooks
from claude_toolkit.hooks import affected_tests, base, format_file, guard, notify, secrets, shell

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CTK_RELAY", raising=False)


def git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    for key, value in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(path), "config", key, value], check=True)
    (path / "a.txt").write_text("one\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)
    return path


def payload(event: str, cwd: Path, session: str = "s1", **fields) -> str:
    return json.dumps({"hook_event_name": event, "session_id": session, "cwd": str(cwd), **fields})


def bash(cwd: Path, command: str) -> str:
    return payload("PreToolUse", cwd, tool_name="Bash", tool_input={"command": command})


# --- plumbing -----------------------------------------------------------------


def test_broken_input_fails_open_and_logs(tmp_path):
    outcome = hooks.dispatch("guard-destructive", "{not json")
    assert (outcome.exit_code, outcome.stdout, outcome.stderr) == (0, "", "")
    assert "JSONDecodeError" in (base.cache_dir() / "errors.log").read_text()


def test_project_file_disables_hooks(tmp_path):
    repo = git_repo(tmp_path / "repo")
    (repo / ".claude-toolkit.toml").write_text('[hooks]\ndisable = ["guard-destructive"]\n')
    assert hooks.dispatch("guard-destructive", bash(repo, "rm -rf /etc")).stdout == ""
    (repo / ".claude-toolkit.toml").write_text("[hooks]\ndisable = true\n")
    assert not base.load_config(repo).enabled("notify")


def test_plugin_hooks_call_existing_ctk_hooks_and_versions_match():
    config = json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())
    commands = [hook["command"] for groups in config["hooks"].values() for g in groups for hook in g["hooks"]]
    named = {command.split("ctk hook ", 1)[1].split(";")[0] for command in commands}
    assert named == set(hooks.HOOKS)
    # Exit 2 from a PreToolUse hook blocks the tool: an old ctk without `hook` must never do that.
    assert all(command.endswith("; exit 0") for command in commands)
    for command in commands:
        done = subprocess.run(["sh", "-c", command.replace("ctk hook", "false")], check=False)
        assert done.returncode == 0
    manifest = json.loads((ROOT / "plugin" / ".claude-plugin" / "plugin.json").read_text())
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert manifest["version"] == __version__
    assert market["plugins"][0]["name"] == manifest["name"] == "ctk"


def test_hook_subcommand_reads_stdin(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(bash(tmp_path, "rm -rf /etc")))
    assert cli.main(["hook", "guard-destructive"]) == 0
    assert "guard-destructive" in json.loads(capsys.readouterr().out)["systemMessage"]


# --- shell parsing --------------------------------------------------------------


def test_split_follows_operators_wrappers_cd_and_nested_shells(tmp_path):
    parsed = shell.split("cd sub && sudo -u root env A=1 rm -rf x 2>/dev/null | bash -c 'git push -f'", tmp_path)
    assert [c.argv for c in parsed] == [["rm", "-rf", "x"], ["git", "push", "-f"]]
    assert parsed[0].cwd == tmp_path / "sub"
    assert shell.expand("$HOME/x", tmp_path) == Path.home() / "x"
    assert shell.expand("$TARGET/x", tmp_path) is None


def test_split_unwraps_xargs_and_its_options(tmp_path):
    parsed = shell.split("ls | xargs -0 -I {} -n1 --max-procs 4 sudo rm -rf {} ; xargs", tmp_path)
    assert [c.argv for c in parsed] == [["ls"], ["rm", "-rf", "{}"]]


# --- guard-destructive ---------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "flagged"),
    [
        ("rm -rf build dist", False),
        ("rm -rf ./node_modules && npm ci", False),
        ("rm -rf *", False),
        ("rm -rf /tmp/ctk-test-temp/build", False),
        ("rm -r ~/notes", False),  # not forced
        ("rm -f ~/notes.txt", False),  # not recursive
        ("echo rm -rf /", False),
        ("git commit -m 'rm -rf / is bad'", False),
        ("rm -rf ~/notes", True),
        ("rm -Rf ../other", True),
        ("rm --recursive --force /etc", True),
        ("rm -rf .", True),  # the project itself
        ("rm -rf /*", True),
        ('rm -rf "$UNKNOWN/dir"', True),
        ("cd .. && rm -rf repo", True),
        ("sudo rm -fr /var/lib/thing", True),
        ("bash -c 'rm -rf ~'", True),
    ],
)
def test_rm_rules(tmp_path, monkeypatch, command, flagged):
    monkeypatch.setattr(guard, "temp_dirs", lambda event: [Path("/tmp/ctk-test-temp")])
    repo = git_repo(tmp_path / "repo")
    event = base.Event.from_json(json.loads(bash(repo, command)))
    assert bool(guard.check(command, event)) is flagged


@pytest.mark.parametrize(
    ("command", "flagged"),
    [
        ("xargs rm -rf build", False),
        ("xargs -0 rm -rf /tmp/ctk-test-temp/x", False),
        ("xargs rm -rf", False),  # no target: the paths come from stdin
        ("xargs rm -r /opt", False),  # not forced
        ("xargs", False),
        ("find build -delete", False),
        ("find . -name '*.pyc' -delete", False),  # find never deletes its own start point
        ("find -name '*.pyc' -delete", False),
        ("find /tmp/ctk-test-temp/build -delete", False),
        ("find /opt -name x", False),
        ("find /opt -exec rm -f {} \\;", False),  # not recursive
        ("find /tmp/ctk-test-temp/x -exec rm -rf {} +", False),
        ("cd sub && find . -delete", False),
        ("xargs rm -rf /opt/y", True),
        ("xargs -0 rm -rf /opt/y", True),
        ("xargs -I {} rm -rf ~/x", True),
        ("xargs -n 1 -P4 --null rm -rf /opt/y", True),
        ("sudo xargs rm -rf /etc", True),
        ("find /opt -delete", True),
        ("find /opt -name x -delete", True),
        ("find -L /opt -delete", True),
        ("find /opt -exec rm -rf {} \\;", True),
        ("find /opt -exec rm -rf {} ';'", True),
        ("find /opt -exec /bin/rm -rf {} +", True),
        ("find build /opt -execdir rm -fr {} +", True),
        ("find .. -delete", True),  # a parent of the project
        ('find "$PWD" -delete', True),  # unlike `.`, find deletes this start point too
        ("find /tmp/ctk-test-temp -exec rm -rf {} +", True),  # passes the temp root itself to rm
        ("bash -c 'find /opt -delete'", True),
    ],
)
def test_xargs_and_find_rules(tmp_path, monkeypatch, command, flagged):
    monkeypatch.setattr(guard, "temp_dirs", lambda event: [Path("/tmp/ctk-test-temp")])
    repo = git_repo(tmp_path / "repo")
    event = base.Event.from_json(json.loads(bash(repo, command)))
    assert bool(guard.check(command, event)) is flagged


def test_find_reasons_name_the_deletion(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "temp_dirs", lambda event: [Path("/tmp/ctk-test-temp")])
    repo = git_repo(tmp_path / "repo")
    event = base.Event.from_json(json.loads(bash(repo, "true")))
    assert guard.check("find /opt -delete", event) == ["`find -delete` outside the project: /opt"]
    assert guard.check("find /opt -exec rm -rf {} +", event) == ["`find -exec rm -rf` outside the project: /opt"]
    assert guard.check("xargs -0 rm -rf /opt/y", event) == ["`rm -rf` outside the project: /opt/y"]


@pytest.mark.parametrize(
    ("command", "flagged"),
    [
        ("git push origin main", False),
        ("git push -f origin feature", False),
        ("git push --force-with-lease origin feat:feat", False),
        ("git push -f origin main", True),
        ("git push --force origin HEAD:refs/heads/master", True),
        ("git push origin +main", True),
        ("git push --force-with-lease", True),  # current branch is main
        ("git -C . push -uf origin main", True),
    ],
)
def test_force_push_rules(tmp_path, command, flagged):
    repo = git_repo(tmp_path / "repo")
    event = base.Event.from_json(json.loads(bash(repo, command)))
    assert bool(guard.check(command, event)) is flagged


def test_reset_hard_only_with_uncommitted_tracked_changes(tmp_path):
    repo = git_repo(tmp_path / "repo")
    event = base.Event.from_json(json.loads(bash(repo, "git reset --hard")))
    (repo / "untracked.txt").write_text("new")
    assert guard.check("git reset --hard HEAD~0", event) == []
    (repo / "a.txt").write_text("changed\n")
    assert "1 tracked file" in guard.check("git reset --hard", event)[0]


def test_warn_mode_runs_and_logs_block_mode_denies(tmp_path):
    repo = git_repo(tmp_path / "repo")
    warned = json.loads(hooks.dispatch("guard-destructive", bash(repo, "rm -rf ~/x")).stdout)
    assert "warn-only" in warned["systemMessage"] and "hookSpecificOutput" not in warned
    assert "rm -rf ~/x" in guard.show_log()
    (repo / ".claude-toolkit.toml").write_text('[hooks.guard-destructive]\nmode = "block"\n')
    blocked = json.loads(hooks.dispatch("guard-destructive", bash(repo, "rm -rf ~/x")).stdout)
    assert blocked["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert hooks.dispatch("guard-destructive", bash(repo, "ls -la")).stdout == ""


# --- secrets --------------------------------------------------------------------

FAKE_GITLEAKS = """#!/bin/sh
if [ "$1" = version ]; then echo 8.21.0; exit 0; fi
while [ $# -gt 0 ]; do
  if [ "$1" = --report-path ]; then shift; report=$1; fi
  shift
done
printf '[{"File":"config.py","StartLine":3,"RuleID":"aws-access-token","Secret":"REDACTED"}]' > "$report"
exit 1
"""


@posix_only
def test_commit_with_a_secret_is_denied_without_showing_it(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / "repo")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gitleaks").write_text(FAKE_GITLEAKS)
    (bin_dir / "gitleaks").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert hooks.dispatch("secrets", bash(repo, "git status")).stdout == ""
    out = json.loads(hooks.dispatch("secrets", bash(repo, "git add . && git commit -m wip")).stdout)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "config.py:3 aws-access-token" in reason and "REDACTED" not in reason


def test_missing_gitleaks_warns_once_per_session(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / "repo")
    monkeypatch.setattr(secrets.shutil, "which", lambda name: None)
    first = hooks.dispatch("secrets", bash(repo, "git commit -m x")).stdout
    assert "gitleaks is not installed" in json.loads(first)["systemMessage"]
    assert hooks.dispatch("secrets", bash(repo, "git commit -m y")).stdout == ""


# --- format-file ------------------------------------------------------------------


def make_ruff_project(root: Path, configured: bool = True) -> Path:
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n" if configured else "[project]\nname='x'\n")
    tool = root / ".venv" / "bin" / "ruff"
    tool.parent.mkdir(parents=True)
    tool.write_text('#!/bin/sh\n[ "$1" = format ] && echo "# formatted" >> "$3"\n')
    tool.chmod(0o755)
    (root / "mod.py").write_text("x=1\n")
    return root


def edit(cwd: Path, file: Path) -> str:
    return payload("PostToolUse", cwd, tool_name="Edit", tool_input={"file_path": str(file)})


@posix_only
def test_formats_only_with_a_configured_formatter(tmp_path):
    project = make_ruff_project(tmp_path / "p")
    assert hooks.dispatch("format-file", edit(project, project / "mod.py")).stdout == ""
    assert (project / "mod.py").read_text().endswith("# formatted\n")
    plain = make_ruff_project(tmp_path / "q", configured=False)
    hooks.dispatch("format-file", edit(plain, plain / "mod.py"))
    assert (plain / "mod.py").read_text() == "x=1\n"


def test_never_formats_outside_the_project(tmp_path):
    project = make_ruff_project(tmp_path / "p")
    other = tmp_path / "elsewhere.py"
    other.write_text("x=1\n")
    hooks.dispatch("format-file", edit(project, other))
    assert other.read_text() == "x=1\n"


@posix_only
def test_formatter_failure_is_reported_to_claude(tmp_path):
    project = make_ruff_project(tmp_path / "p")
    (project / ".venv" / "bin" / "ruff").write_text("#!/bin/sh\necho 'error: invalid syntax at 1:3' >&2\nexit 2\n")
    out = json.loads(hooks.dispatch("format-file", edit(project, project / "mod.py")).stdout)
    assert "invalid syntax" in out["hookSpecificOutput"]["additionalContext"]


def test_formatter_table_covers_common_ecosystems(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n")
    (tmp_path / "main.go").write_text("package main\n")
    found = format_file.formatter_for(tmp_path / "main.go", tmp_path)
    assert found is None or found[0] == "gofmt"
    assert format_file.formatter_for(tmp_path / "notes.txt", tmp_path) is None


# --- affected-tests ---------------------------------------------------------------


def test_python_sources_map_to_their_tests(tmp_path):
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    for name in ("src/pkg/util.py", "src/pkg/__init__.py", "tests/test_util.py", "tests/test_pkg.py", "tests/x.py"):
        (tmp_path / name).write_text("")
    edited = [tmp_path / "src/pkg/util.py", tmp_path / "src/pkg/__init__.py", tmp_path / "tests/test_util.py"]
    found = affected_tests.python_tests(edited, tmp_path)
    assert sorted(path.name for path in found) == ["test_pkg.py", "test_util.py"]


def test_failures_block_once_then_only_warn(tmp_path, monkeypatch):
    project = tmp_path / "p"
    project.mkdir()
    source = project / "mod.py"
    source.write_text("")
    failing = affected_tests.Plan("pytest", [sys.executable, "-c", "print('FAILED test_mod.py::t'); exit(1)"], project)
    monkeypatch.setattr(affected_tests, "plans_for", lambda files, root: [failing])

    assert hooks.dispatch("affected-tests", edit(project, source)).stdout == ""
    first = json.loads(hooks.dispatch("affected-tests", payload("Stop", project, stop_hook_active=False)).stdout)
    assert first["decision"] == "block" and "FAILED test_mod.py::t" in first["reason"]
    again = json.loads(hooks.dispatch("affected-tests", payload("Stop", project, stop_hook_active=True)).stdout)
    assert "decision" not in again and "still fail" in again["systemMessage"]
    assert hooks.dispatch("affected-tests", payload("Stop", project)).stdout == ""  # nothing left to run


def test_passing_tests_and_no_edits_are_silent(tmp_path, monkeypatch):
    project = tmp_path / "p"
    project.mkdir()
    (project / "mod.py").write_text("")
    passing = affected_tests.Plan("pytest", [sys.executable, "-c", "pass"], project)
    monkeypatch.setattr(affected_tests, "plans_for", lambda files, root: [passing])
    assert hooks.dispatch("affected-tests", payload("Stop", project)).stdout == ""
    hooks.dispatch("affected-tests", edit(project, project / "mod.py"))
    assert hooks.dispatch("affected-tests", payload("Stop", project)).stdout == ""


# --- notify -----------------------------------------------------------------------


def test_notify_waits_for_long_turns_and_rate_limits(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send", lambda title, body: sent.append(body) or True)
    clock = [1000.0]
    monkeypatch.setattr(notify.time, "time", lambda: clock[0])
    assert hooks.dispatch("notify", payload("UserPromptSubmit", tmp_path, prompt="hi")).stdout == ""
    clock[0] += 10
    hooks.dispatch("notify", payload("Stop", tmp_path))
    assert sent == []  # short turn
    clock[0] += 100
    hooks.dispatch("notify", payload("Stop", tmp_path))
    assert sent == ["Done after 1m 50s"]
    hooks.dispatch("notify", payload("Notification", tmp_path, message="Claude needs your permission"))
    assert len(sent) == 1  # within a minute of the last one


def test_this_repository_maps_runq_to_its_tests():
    plans = affected_tests.plans_for([ROOT / "src" / "claude_toolkit" / "runq.py"], ROOT)
    if not plans:
        pytest.skip("no project .venv with pytest (for example a non-uv environment)")
    assert plans[0].cwd == ROOT and plans[0].command[-1] == "tests/test_runq.py"


# --- continuity ---------------------------------------------------------------------


def compact(cwd, source="compact"):
    return json.dumps({"hook_event_name": "SessionStart", "source": source, "session_id": "s", "cwd": str(cwd)})


def test_continuity_only_after_compaction_and_only_with_something_to_say(tmp_path):
    repo = git_repo(tmp_path / "repo")
    assert hooks.dispatch("continuity", compact(repo, "startup")).stdout == ""
    assert hooks.dispatch("continuity", compact(repo)).stdout == "", "clean tree, no checks, no handoff"
    assert hooks.dispatch("continuity", compact(tmp_path)).stdout == "", "not a git repository"


def test_continuity_brings_back_branch_checks_and_handoff(tmp_path, monkeypatch):
    from claude_toolkit import verify

    repo = git_repo(tmp_path / "repo")
    subprocess.run(["git", "-C", str(repo), "switch", "-q", "-c", "feat/x"], check=True)
    verify.record([sys.executable, "-c", "print('3 passed')"], repo, 0, "3 passed in 0.1s\n", 0.1)
    handoff = repo / ".claude" / "handoff" / "feat-x.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text("# feat/x — goal\n\n## Next\n1. finish the parser\n")
    out = json.loads(hooks.dispatch("continuity", compact(repo)).stdout)
    text = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "branch feat/x" in text and "finish the parser" in text and "written just now" in text
    assert "~ stale" in text, "the handoff file itself changed the tree after the check ran"


def test_notify_on_windows_passes_the_text_through_the_environment(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.platform, "system", lambda: "Windows")
    monkeypatch.setattr(notify.shutil, "which", lambda name: f"C:/Windows/{name}.exe")
    monkeypatch.setattr(notify.subprocess, "run", lambda command, **kw: calls.append((command, kw["env"])))
    title, body = "Claude Code", "done'; Remove-Item -Recurse C:\\ #"
    assert notify.send(title, body)
    (command, env), *_ = calls
    assert command[0] == "powershell" and body not in " ".join(command), "the text never becomes script"
    assert env["CTK_NOTIFY_TITLE"] == title and env["CTK_NOTIFY_BODY"] == body
