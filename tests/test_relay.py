import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from claude_toolkit import cli, hooks, relay, sessions
from claude_toolkit.hooks import relay as relay_hook
from claude_toolkit.hooks import runq_nudge


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for name in ("CLAUDE_PROJECT_DIR", "CLAUDE_CODE_SESSION_ID", "CLAUDE_EFFORT", "CTK_RELAY", "CTK_RELAY_FROM"):
        monkeypatch.delenv(name, raising=False)


def git_repo(path: Path, branch: str = "feat/x") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    for key, value in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(path), "config", key, value], check=True)
    (path / "a.txt").write_text("one\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)
    subprocess.run(["git", "-C", str(path), "switch", "-q", "-c", branch], check=True)
    return path


def write_handoff(repo: Path, age: float = 0) -> Path:
    handoff = repo / ".claude" / "handoff" / "feat-x.md"
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text("# feat/x — goal\n\n## Next\n1. finish the parser\n")
    if age:
        old = time.time() - age
        os.utime(handoff, (old, old))
    return handoff


# --- terminal and command ------------------------------------------------------------


def installed(*names):
    return lambda name: f"/usr/bin/{name}" if name in names else None


def test_detect_terminal_prefers_the_one_claude_runs_in():
    env = {"KONSOLE_VERSION": "1", "DISPLAY": ":0"}

    def detect(env, which):
        return relay.detect_terminal(env, which, system="Linux")

    assert detect(env, installed("konsole", "alacritty")) == "konsole"
    assert detect({"TMUX": "/tmp/t", **env}, installed("tmux", "konsole")) == "tmux"
    assert detect(env, installed("alacritty")) == "alacritty", "marker without binary: fall back"
    assert detect({}, installed("alacritty")) is None, "no display, no graphical terminal"
    assert detect({"WAYLAND_DISPLAY": "w"}, installed()) is None


def test_detect_terminal_on_macos_and_windows():
    mac = installed("osascript")
    assert relay.detect_terminal({"TERM_PROGRAM": "iTerm.app"}, mac, system="Darwin") == "iterm"
    assert relay.detect_terminal({"TERM_PROGRAM": "vscode"}, mac, system="Darwin") == "terminal"
    assert relay.detect_terminal({}, installed(), system="Darwin") is None
    assert relay.detect_terminal({"WT_SESSION": "x"}, installed("wt", "powershell"), system="Windows") == "wt"
    assert relay.detect_terminal({}, installed("powershell"), system="Windows") == "console"


def test_terminals_that_do_not_inherit_the_environment_carry_it(tmp_path):
    import base64

    cwd = tmp_path / "it's here"
    env = {"CTK_RELAY": "1", "CTK_RELAY_FROM": "old"}
    command = ["claude", "--name", "relay feat/x", "Continue (ctk relay); run `ctk relay --show`"]
    osa = relay.terminal_command("terminal", cwd, command, env)
    assert osa[0] == "osascript" and 'do script "cd ' in osa[2]
    assert "env CTK_RELAY=1 CTK_RELAY_FROM=old claude --name" in osa[2]
    iterm = relay.terminal_command("iterm", cwd, command, env)
    assert "create window with default profile command" in iterm[2] and "/bin/sh -c" in iterm[2]
    wt = relay.terminal_command("wt", cwd, command, env)
    assert wt[:3] == ["wt", "-d", str(cwd)] and wt[3] == "powershell" and wt[-2] == "-EncodedCommand"
    script = base64.b64decode(wt[-1]).decode("utf-16-le")
    assert "$env:CTK_RELAY = '1'" in script and "$env:CTK_RELAY_FROM = 'old'" in script
    assert f"Set-Location -LiteralPath '{str(cwd).replace(chr(39), chr(39) * 2)}'" in script
    assert "& 'claude' '--name' 'relay feat/x' 'Continue (ctk relay); run `ctk relay --show`'" in script
    assert relay.terminal_command("console", cwd, command, env)[0] == "powershell"
    assert relay.terminal_command("konsole", cwd, ["claude"], env)[-1] == "claude", "inheriting ones need nothing"


def test_commands_and_environment_of_the_new_session(tmp_path):
    command = relay.claude_command("feat/x", {"CLAUDE_EFFORT": "high"}, ["--model", "opus"])
    assert command[:5] == ["claude", "--name", "relay feat/x", "--effort", "high"]
    assert command[5:7] == ["--model", "opus"] and command[-1] == relay.FIRST_PROMPT
    full = relay.terminal_command("konsole", tmp_path, ["claude"])
    assert full == ["konsole", "--workdir", str(tmp_path), "-e", "claude"]
    assert relay.terminal_command(["foot", "-D", "{cwd}"], tmp_path, ["claude"]) == [
        "foot",
        "-D",
        str(tmp_path),
        "claude",
    ]
    assert relay.terminal_command("nope", tmp_path, ["claude"]) is None
    env = relay.child_env({"PATH": "/bin", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "old", "CTK_RELAY": "x"}, "old")
    assert env == {"PATH": "/bin", "CTK_RELAY": "1", "CTK_RELAY_FROM": "old"}


# --- ctk relay -----------------------------------------------------------------------


@pytest.fixture
def launched(monkeypatch):
    calls = []

    def fake_launch(command, cwd, env, new_console=False):
        calls.append((command, cwd, env))
        return None

    monkeypatch.setattr(relay, "_launch", fake_launch)
    monkeypatch.setattr(relay.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setenv("KONSOLE_VERSION", "1")
    return calls


def ctk(repo, monkeypatch, *args):
    monkeypatch.chdir(repo)
    return cli.main(["relay", *args])


def test_relay_needs_a_repository_and_a_fresh_handoff(tmp_path, monkeypatch, capsys, launched):
    assert ctk(tmp_path, monkeypatch, "--yes") == 1
    assert "/clear" in capsys.readouterr().out
    repo = git_repo(tmp_path / "repo")
    assert ctk(repo, monkeypatch, "--yes") == 1
    assert "no handoff file for feat/x" in capsys.readouterr().out
    write_handoff(repo, age=3600)
    assert ctk(repo, monkeypatch, "--yes") == 1
    assert "60 minutes ago" in capsys.readouterr().out
    assert launched == []


def test_relay_without_a_terminal_falls_back_to_clear(tmp_path, monkeypatch, capsys):
    repo = git_repo(tmp_path / "repo")
    write_handoff(repo)
    monkeypatch.setattr(relay, "detect_terminal", lambda env: None)
    assert ctk(repo, monkeypatch, "--yes") == 1
    assert "type /clear" in capsys.readouterr().out


def test_relay_asks_first_and_exits_3_without_a_terminal(tmp_path, monkeypatch, capsys, launched):
    repo = git_repo(tmp_path / "repo")
    write_handoff(repo)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "old")
    monkeypatch.setattr("sys.stdin", open(os.devnull))  # noqa: SIM115
    assert ctk(repo, monkeypatch) == 3
    out = capsys.readouterr()
    assert "konsole --workdir" in out.out and "confirmation required" in out.err
    assert ctk(repo, monkeypatch, "--dry-run") == 0
    assert launched == [] and not relay.locked("old")


def test_relay_opens_the_session_and_locks_the_old_one(tmp_path, monkeypatch, capsys, launched):
    repo = git_repo(tmp_path / "repo")
    write_handoff(repo)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "old")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert ctk(repo, monkeypatch, "--yes") == 0
    assert "End your turn now" in capsys.readouterr().out
    (command, cwd, env), *_ = launched
    assert command[:4] == ["konsole", "--workdir", str(repo), "-e"] and command[4] == "claude"
    assert cwd == repo and env["CTK_RELAY_FROM"] == "old" and "CLAUDECODE" not in env
    assert relay.locked("old")
    assert ctk(repo, monkeypatch, "--release") == 0
    assert not relay.locked("old")


def test_relay_config_auto_and_terminal(tmp_path, monkeypatch, launched):
    repo = git_repo(tmp_path / "repo")
    write_handoff(repo)
    (repo / ".claude-toolkit.toml").write_text('[relay]\nauto = true\nterminal = ["foot", "-D", "{cwd}"]\n')
    monkeypatch.setattr("sys.stdin", open(os.devnull))  # noqa: SIM115
    assert ctk(repo, monkeypatch) == 0, "auto = true needs no terminal to confirm"
    assert launched[0][0][:4] == ["foot", "-D", str(repo), "claude"]


def test_relay_reports_a_terminal_that_fails(tmp_path, monkeypatch, capsys, launched):
    repo = git_repo(tmp_path / "repo")
    write_handoff(repo)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "old")
    monkeypatch.setattr(relay, "_launch", lambda *a, **k: "konsole exited with 1")
    assert ctk(repo, monkeypatch, "--yes") == 1
    assert "could not open" in capsys.readouterr().out and not relay.locked("old")


def test_launch_detects_immediate_failure(tmp_path):
    assert relay._launch(["false"], tmp_path, dict(os.environ)) == "false exited with 1"
    assert relay._launch(["/nonexistent/terminal"], tmp_path, dict(os.environ))
    assert relay._launch(["true"], tmp_path, dict(os.environ)) is None


def test_relay_show_prints_the_brief(tmp_path, monkeypatch, capsys):
    repo = git_repo(tmp_path / "repo")
    write_handoff(repo)
    assert ctk(repo, monkeypatch, "--show") == 0
    out = capsys.readouterr().out
    assert "handed over by ctk relay" in out and "finish the parser" in out and "Resume from the handoff" in out


# --- continuity on clear, resume and relay ---------------------------------------------


def start(cwd, source):
    return json.dumps({"hook_event_name": "SessionStart", "source": source, "session_id": "s", "cwd": str(cwd)})


def context(outcome):
    return json.loads(outcome.stdout)["hookSpecificOutput"]["additionalContext"]


def test_continuity_after_clear_resume_and_relay(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / "repo")
    assert hooks.dispatch("continuity", start(repo, "startup")).stdout == "", "a plain start says nothing"
    monkeypatch.setenv("CTK_RELAY", "1")
    text = context(hooks.dispatch("continuity", start(repo, "startup")))
    assert "handed over by ctk relay" in text and "Resume from the handoff" in text, "even on a clean tree"
    monkeypatch.delenv("CTK_RELAY")
    write_handoff(repo)
    assert "after /clear" in context(hooks.dispatch("continuity", start(repo, "clear")))
    assert "on resume" in context(hooks.dispatch("continuity", start(repo, "resume")))
    assert "after a compaction" in context(hooks.dispatch("continuity", start(repo, "compact")))


# --- relay hook ------------------------------------------------------------------------


def transcript(path: Path, windows: list[int]) -> Path:
    records = [{"type": "user", "message": {"content": "hi"}}]
    for i, window in enumerate(windows):
        usage = {"input_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": window - 10}
        records.append({"type": "assistant", "message": {"id": f"m{i}", "usage": usage}})
    records.append({"type": "assistant", "isSidechain": True, "message": {"usage": {"input_tokens": 999_999}}})
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def stop(cwd, path, session="s1", **fields):
    return json.dumps(
        {"hook_event_name": "Stop", "session_id": session, "cwd": str(cwd), "transcript_path": str(path), **fields}
    )


def edit(cwd, session="s1", tool="Edit"):
    return json.dumps(
        {"hook_event_name": "PreToolUse", "session_id": session, "cwd": str(cwd), "tool_name": tool, "tool_input": {}}
    )


def test_current_window_reads_the_last_main_thread_call(tmp_path):
    assert relay_hook.current_window(transcript(tmp_path / "t.jsonl", [1000, 250_000])) == 250_000
    assert relay_hook.current_window(tmp_path / "missing.jsonl") is None


def test_relay_hook_asks_once_above_the_threshold(tmp_path):
    small = transcript(tmp_path / "small.jsonl", [200_000])
    large = transcript(tmp_path / "large.jsonl", [200_000, 310_000])
    assert hooks.dispatch("relay", stop(tmp_path, small)).stdout == ""
    assert hooks.dispatch("relay", stop(tmp_path, large, stop_hook_active=True)).stdout == ""
    out = json.loads(hooks.dispatch("relay", stop(tmp_path, large)).stdout)
    assert out["decision"] == "block" and "310,000" in out["reason"] and "ctk relay" in out["reason"]
    assert hooks.dispatch("relay", stop(tmp_path, large)).stdout == "", "once per session"
    assert hooks.dispatch("relay", stop(tmp_path, large, session="s2")).stdout != ""


def test_relay_hook_threshold_is_configurable(tmp_path):
    (tmp_path / ".claude-toolkit.toml").write_text("[hooks.relay]\nthreshold = 500000\n")
    large = transcript(tmp_path / "t.jsonl", [310_000])
    assert hooks.dispatch("relay", stop(tmp_path, large)).stdout == ""


def test_relay_hook_denies_edits_of_a_relayed_session(tmp_path):
    assert hooks.dispatch("relay", edit(tmp_path)).stdout == ""
    relay.lock("s1", "konsole")
    out = json.loads(hooks.dispatch("relay", edit(tmp_path)).stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "--release --session s1" in out["permissionDecisionReason"]
    assert hooks.dispatch("relay", edit(tmp_path, tool="Read")).stdout == ""
    assert hooks.dispatch("relay", edit(tmp_path, session="s2")).stdout == ""
    large = transcript(tmp_path / "t.jsonl", [400_000])
    assert hooks.dispatch("relay", stop(tmp_path, large)).stdout == "", "already relayed: nothing to ask"


# --- runq-nudge ------------------------------------------------------------------------


def bash_done(cwd, command, output, session="s1"):
    return json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "session_id": session,
            "cwd": str(cwd),
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": {"stdout": output, "stderr": "", "interrupted": False},
        }
    )


def test_runq_nudge_once_per_command_for_long_output(tmp_path):
    long = "x" * 9_000
    assert hooks.dispatch("runq-nudge", bash_done(tmp_path, "pytest", "short")).stdout == ""
    assert hooks.dispatch("runq-nudge", bash_done(tmp_path, "ctk runq -- pytest", long)).stdout == ""
    text = context(hooks.dispatch("runq-nudge", bash_done(tmp_path, "uv run pytest -q", long)))
    assert "ctk runq -- <command>" in text and "~2,250 tokens" in text
    assert hooks.dispatch("runq-nudge", bash_done(tmp_path, "cd x && uv run pytest", long)).stdout == ""
    for command in ("cargo test", "npm test"):
        assert hooks.dispatch("runq-nudge", bash_done(tmp_path, command, long)).stdout != ""
    assert hooks.dispatch("runq-nudge", bash_done(tmp_path, "make", long)).stdout == "", "at most 3 per session"


def test_runq_nudge_command_name():
    assert runq_nudge.command_name("cd src && FOO=1 uv run pytest -q") == "pytest"
    assert runq_nudge.command_name("python -m pytest") == "python"
    assert runq_nudge.output_chars({"stdout": "ab", "stderr": "c"}) == 3


# --- relay point in ctk sessions ---------------------------------------------------------


def session(windows, first_edit=None):
    s = sessions.Session("p")
    s.windows = windows
    s.first_edit_window = first_edit
    return s


def test_replay_resets_the_window_at_each_relay():
    cost, relays = sessions.replay([100, 200, 300, 400, 500], threshold=300, restart=50)
    # 100 + 200, relay at 300 (2 turns x 300 + 12.5 x 50 write, then 50), then 150 and 250
    assert relays == 1 and cost == 100 + 200 + 600 + 625 + 50 + 150 + 250
    assert sessions.replay([100, 200], threshold=300, restart=50) == (300, 0)


def test_relay_point_from_long_and_short_sessions():
    growing = [20_000 + 10_000 * i for i in range(90)]  # up to ~910k
    point = sessions.relay_point([session(growing, first_edit=40_000), session([30_000, 40_000])])
    assert point.threshold is not None and point.saving > 0.3
    assert point.restart_window == 40_000 + sessions.HANDOFF_TOKENS and point.sessions == 1
    assert sessions.relay_point([session([30_000, 40_000])]).threshold is None, "short sessions never relay"
    assert sessions.relay_point([]).threshold is None


def test_sessions_report_shows_the_relay_point(tmp_path):
    records = []
    for i in range(60):
        usage = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 30_000 + 15_000 * i}
        records.append(
            {"type": "assistant", "timestamp": "2026-10-01T10:00:00Z", "message": {"id": f"m{i}", "usage": usage}}
        )
    path = tmp_path / "-p" / "s.jsonl"
    path.parent.mkdir()
    path.write_text("\n".join(json.dumps(r) for r in records))
    summary = sessions.summarise([sessions.parse_session(path)])
    assert summary.median_window_growth == 15_000 and summary.relay_threshold
    text = sessions.render(summary, "test", style=None)
    assert "relay point" in text and f"{summary.relay_threshold:,} tokens" in text


# --- close-old -------------------------------------------------------------------------


posix = pytest.mark.skipif(os.name == "nt", reason="closing the old window is POSIX only")


@posix
def test_close_target_is_the_shell_running_claude_else_claude():
    tree = {10: (5, "claude"), 5: (2, "zsh"), 20: (2, "claude"), 2: (1, "konsole")}
    assert relay.close_target({"CLAUDE_PID": "10"}, tree.get) == (5, "zsh")
    assert relay.close_target({"CLAUDE_PID": "20"}, tree.get) == (20, "claude"), "run by the terminal itself"
    assert relay.close_target({"CLAUDE_PID": "5"}, tree.get) is None, "not claude: never hang it up"
    assert relay.close_target({}, tree.get) is None


@posix
def test_close_later_hangs_up_only_the_recorded_process(tmp_path):
    process = subprocess.Popen(["sleep", "30"])
    try:
        assert not relay.close_later(process.pid, "bash", delay=0), "a reused pid is left alone"
        assert relay.close_later(process.pid, "sleep", delay=0)
        assert process.wait(timeout=5) == -signal.SIGHUP
    finally:
        process.kill()


def test_relay_close_old_closes_the_window_when_the_turn_ends(tmp_path, monkeypatch, capsys, launched):
    repo = git_repo(tmp_path / "repo")
    write_handoff(repo)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "old")
    monkeypatch.setattr(relay, "close_target", lambda env: (4242, "zsh"))
    assert ctk(repo, monkeypatch, "--yes") == 0
    assert "closes when the turn ends" not in capsys.readouterr().out, "off by default"
    relay.release("old")
    (repo / ".claude-toolkit.toml").write_text("[relay]\nclose-old = true\n")
    assert ctk(repo, monkeypatch, "--yes") == 0
    assert "This window closes when the turn ends" in capsys.readouterr().out
    closed = []
    monkeypatch.setattr(relay, "close_later", lambda pid, name: closed.append((pid, name)))
    large = transcript(tmp_path / "t.jsonl", [400_000])
    assert hooks.dispatch("relay", stop(repo, large, session="old")).stdout == ""
    assert hooks.dispatch("relay", stop(repo, large, session="old")).stdout == ""
    assert closed == [(4242, "zsh")], "closed once, at the end of the turn"
