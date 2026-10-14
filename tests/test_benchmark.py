import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bench", ROOT / "benchmark" / "run.py")
bench = importlib.util.module_from_spec(spec)
sys.modules["bench"] = bench  # dataclasses look their module up while the file executes
spec.loader.exec_module(bench)


def test_frontmatter_subset():
    meta, body = bench.parse_frontmatter(
        '---\nruns: 3\nplugins: ["../../../plugin"]\ntarget: { source: file, path: OUT.txt }\n'
        "flags: i\ntags:\n  - a\n  - b\n---\n\nDo it.\n"
    )
    assert meta == {"runs": 3, "plugins": ["../../../plugin"], "target": {"source": "file", "path": "OUT.txt"},
                    "flags": "i", "tags": ["a", "b"]}  # fmt: skip
    assert body == "Do it."


@pytest.mark.parametrize("case", sorted(p.name for p in (ROOT / "benchmark" / "cases").iterdir()))
def test_every_case_loads_and_is_eval_compatible(case):
    loaded = bench.load_case(ROOT / "benchmark" / "cases" / case)
    assert loaded.prompt and loaded.setup is not None and loaded.graders
    assert {g.type for g in loaded.graders} <= {"regex", "tool_used", "file_exists", "check"}
    meta, _ = bench.parse_frontmatter((ROOT / "benchmark" / "cases" / case / "prompt.md").read_text())
    # `claude plugin eval` rejects unknown prompt.md keys.
    allowed = {"schema_version", "name", "description", "tags", "plugins", "runs", "expected_outcome", "model",
               "max_turns", "timeout_seconds", "allowed_tools", "append_system_prompt", "env"}  # fmt: skip
    assert set(meta) <= allowed and meta["plugins"] == ["../../../plugin"]


def usage(fresh, written, read, out):
    keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
    return dict(zip(keys, (fresh, written, read, out), strict=True))


RUNQ = {"type": "tool_use", "name": "Bash", "input": {"command": "ctk runq -- python3 run_tests.py"}}
STREAM = [
    {"type": "system", "subtype": "init"},
    {"type": "assistant", "message": {"id": "m1", "content": [RUNQ], "usage": usage(10, 1000, 0, 5)}},
    {
        "type": "assistant",
        "message": {"id": "m1", "content": [{"type": "text", "text": "…"}], "usage": usage(10, 1000, 0, 5)},
    },
    {
        "type": "assistant",
        "message": {"id": "m2", "content": [{"type": "text", "text": "done"}], "usage": usage(2, 50, 1000, 40)},
    },
    {
        "type": "result",
        "result": "Fixed both bugs; the secret key was blocked.",
        "total_cost_usd": 0.12,
        "num_turns": 3,
    },
]


def transcript():
    return bench.Transcript.parse("\n".join(json.dumps(line) for line in STREAM) + "\nnot json\n")


def test_transcript_counts_each_message_once():
    t = transcript()
    assert t.usage == {"input_tokens": 12, "cache_creation_input_tokens": 1050, "cache_read_input_tokens": 1000,
                       "output_tokens": 45}  # fmt: skip
    assert t.context_tokens == 2062 and t.cost == 0.12 and t.turns == 3
    assert t.tool_calls == [("Bash", {"command": "ctk runq -- python3 run_tests.py"})]


def grade(kind, files=None, created=(), check=(0, "ok"), **options):
    grader = bench.Grader("g", kind, options)
    files = files or {}
    return bench.grade(grader, transcript(), files.get, lambda script: check, list(created))


def test_graders():
    assert grade("regex", pattern="secret", flags="i")[0]
    assert not grade("regex", pattern="SECRET")[0]
    assert grade("regex", pattern="zzz", match="not_contains")[0]
    assert grade(
        "regex", files={"R.txt": "900 passed"}, target={"source": "file", "path": "R.txt"}, pattern=r"\d+ passed"
    )[0]
    assert grade("regex", target={"source": "file", "path": "missing"}, pattern=".")[1] == "missing does not exist"
    assert grade("regex", target="trace", pattern="ctk runq")[0]
    assert grade("tool_used", tool="Bash", input_match="runq")[0]
    assert not grade("tool_used", tool="Bash", input_match="libdocs")[0]
    assert grade("tool_used", tool="Edit", min=0, max=0)[0]
    assert grade("file_exists", path="*.txt", created=["RESULT.txt"])[0]
    assert grade("check", check=(1, "the suite still fails\n"), script="x.sh") == (False, "the suite still fails")


def test_with_only_graders_do_not_count_in_two_arm_runs():
    graders = [bench.Grader("result", "regex", {}), bench.Grader("used", "tool_used", {}, arm="with-only")]
    verdicts = [{"passed": True}, {"passed": False}]
    assert bench.score(verdicts, graders, two_arms=True) == 1.0
    assert bench.score(verdicts, graders, two_arms=False) == 0.5


def test_summary_reports_score_and_token_deltas():
    case = bench.Case("c", ROOT, "p")
    make = lambda arm, s, tok: bench.RunResult("c", arm, 1, s, [], tok, 10, {}, 0.1, 3, 1.0, None, "x")  # noqa: E731
    rows, table = bench.summarise([make("with", 1.0, 5000), make("without", 0.5, 10000)], [case], ["with", "without"])
    assert rows[0]["with"]["context_tokens"] == 5000
    assert "+0.50" in table and "-50%" in table


def test_credentials_come_from_env_file_or_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "HERE", tmp_path)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert bench.load_credentials() == {}
    (tmp_path / ".env").write_text("# comment\nCLAUDE_CODE_OAUTH_TOKEN='abc'\nOTHER=ignored\n")
    assert bench.load_credentials() == {"CLAUDE_CODE_OAUTH_TOKEN": "abc"}


def test_an_empty_transcript_has_zero_usage():
    assert bench.Transcript([]).context_tokens == 0


def test_failed_runs_are_counted_but_not_scored():
    case = bench.Case("c", ROOT, "p")
    ok = bench.RunResult("c", "with", 1, 1.0, [], 5000, 10, {}, 0.1, 3, 1.0, None, "x")
    broken = bench.RunResult("c", "with", 2, 0.5, [], 0, 0, {}, 0.0, 1, 1.0, "You've hit your session limit", "y")
    rows, _ = bench.summarise([ok, broken], [case], ["with"])
    assert rows[0]["with"] == {"score": 1.0, "context_tokens": 5000, "output_tokens": 10, "cost": 0.1, "turns": 3.0,
                               "errors": 1, "runs": 1}  # fmt: skip
    assert bench.LIMIT_ERRORS.search(broken.error)


def test_error_results_keep_their_message():
    line = {"type": "result", "subtype": "success", "is_error": True, "result": "You've hit your session limit"}
    assert bench.Transcript.parse(json.dumps(line)).error == "You've hit your session limit"


def test_case_env_reaches_the_claude_process_in_both_arms():
    case = bench.load_case(ROOT / "benchmark" / "cases" / "relay-resume")
    assert case.env == {"CTK_RELAY": "1"}
    for arm in ("with", "without"):
        command = bench.claude_command(case, "box", arm)
        assert command[:5] == ["exec", "-w", "/work", "-e", "CTK_RELAY=1"], "options come before the container name"
        assert command[5:7] == ["box", "claude"] and case.prompt in command
        assert ("--plugin-dir" in command) == (arm == "with")
    assert (
        "-e"
        not in bench.claude_command(bench.load_case(ROOT / "benchmark" / "cases" / "secret-commit"), "box", "with")[:6]
    )
    assert command[command.index("--max-turns") + 1] == str(case.max_turns)
