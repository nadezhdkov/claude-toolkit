import sys

from claude_toolkit import runq


def pytest_output(failures: int, passed: int = 1000) -> str:
    lines = ["============================= test session starts =============================="]
    lines += [f"tests/test_mod.py::test_case_{i} PASSED" for i in range(passed)]
    lines.append("=========================== short test summary info ============================")
    lines += [f"FAILED tests/test_mod.py::test_bad_{i} - AssertionError: boom {i}" for i in range(failures)]
    lines.append(f"================= {failures} failed, {passed} passed in 12.34s =================")
    return "\n".join(lines)


def test_short_output_is_printed_unchanged():
    text = runq.summarise(["echo"], "hello\nworld\n", 0, None)
    assert text.splitlines() == ["hello", "world", "runq: exit 0 · 2 lines"]


def test_500_pytest_failures_fit_in_80_lines_with_correct_count(tmp_path):
    text = runq.summarise(["pytest"], pytest_output(500), 1, tmp_path / "x.log")
    lines = text.splitlines()
    assert len(lines) < 80
    assert lines[0].startswith("runq: exit 1 · 1503 lines · log:")
    shown = [line for line in lines if line.startswith("FAILED ")]
    assert shown and all("test_bad_" in line for line in shown)
    assert "failures counted: 500" in text
    assert "500 failed, 1000 passed" in text


def test_extractor_is_chosen_from_output_when_command_is_generic():
    text = runq.summarise(["make", "test"], pytest_output(3), 2, None)
    assert "[pytest]" in text and text.count("FAILED ") == 3


def test_quiet_pytest_summary_is_recognised():
    output = "\n".join(
        ["." * 80] * 70 + ["FAILED tests/test_a.py::test_x - assert 1 == 2", "1 failed, 69 passed in 0.50s"]
    )
    text = runq.summarise(["pytest", "-q"], output, 1, None)
    assert text.splitlines()[-1] == "1 failed, 69 passed in 0.50s"


def test_typescript_errors():
    output = "\n".join(
        [f"src/a{i}.ts(1,1): error TS2322: Type 'string' is not assignable" for i in range(70)] + ["Found 70 errors."]
    )
    text = runq.summarise(["npx", "tsc", "--noEmit"], output, 2, None)
    assert "[tsc]" in text and "Found 70 errors." in text and "failures counted: 70" in text


def test_unknown_tool_falls_back_to_error_lines_and_tail():
    output = "\n".join([f"step {i}" for i in range(100)] + ["fatal: something broke"])
    text = runq.summarise(["./build.sh"], output, 1, None)
    assert "[generic]" in text and "fatal: something broke" in text
    assert "--- last 40 lines ---" not in text


def test_failure_without_recognisable_lines_shows_the_tail():
    output = "\n".join(f"line {i}" for i in range(200))
    text = runq.summarise(["./thing"], output, 3, None)
    assert "--- last 40 lines ---" in text and "line 199" in text


def test_ansi_colours_are_stripped():
    assert "\x1b" not in runq.summarise(["x"], "\x1b[31mred\x1b[0m\n", 0, None)


def test_run_preserves_exit_code_and_writes_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    code = runq.run([sys.executable, "-c", "print('hi'); raise SystemExit(7)"])
    assert code == 7
    out = capsys.readouterr().out
    assert "hi" in out and "runq: exit 7" in out
    logs = list((tmp_path / "claude-toolkit" / "runq").glob("*.log"))
    assert len(logs) == 1 and "hi" in logs[0].read_text()


def test_missing_command_returns_127(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert runq.run(["definitely-not-a-command-xyz"]) == 127


def test_old_logs_are_pruned(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    for _ in range(3):
        runq.run([sys.executable, "-c", "print(1)"], keep_logs=2)
    assert len(list((tmp_path / "claude-toolkit" / "runq").glob("*.log"))) <= 2
