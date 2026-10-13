import json
import subprocess
import textwrap

import pytest

from claude_toolkit import cli, diffcheck


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@e.st"), ("user.name", "t"), ("commit.gpgsign", "false")):
        git(root, "config", key, value)
    write(
        root,
        "app/engine.py",
        """\
        class Engine:
            def start(self, speed): ...

        def build_engine(config): ...

        def unused_helper(): ...
        """,
    )
    write(root, "app/cli.py", "from app.engine import build_engine\n\ndef main():\n    build_engine({})\n")
    write(root, "tests/test_engine.py", "from app.engine import Engine\n")
    write(root, "package-lock.json", "{}\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "base")
    monkeypatch.chdir(root)
    return root


def run(root):
    base = diffcheck.default_base(root)
    _, findings = diffcheck.check(root, base)
    return {(f.level, f.kind, f.path, f.line): f.message for f in findings}


def test_clean_tree_has_nothing_to_flag(repo, capsys):
    assert run(repo) == {}
    assert cli.main(["diffcheck"]) == 0
    assert "nothing to flag" in capsys.readouterr().out


def test_removed_api_still_in_use_is_high_and_fails(repo, capsys):
    write(
        repo,
        "app/engine.py",
        """\
        class Engine:
            def start(self, speed, *, warm=False): ...
        """,
    )
    found = run(repo)
    assert "app/cli.py:1" in found[("high", "api", "app/engine.py", 4)]
    assert found[("warn", "api", "app/engine.py", 6)] == "public `unused_helper` removed"
    assert cli.main(["diffcheck"]) == 1
    assert "removed `build_engine` is still used" in capsys.readouterr().out


def test_signature_change(repo):
    write(
        repo,
        "app/engine.py",
        """\
        class Engine:
            def start(self, speed): ...

        def build_engine(config, *, strict=False): ...

        def unused_helper(): ...
        """,
    )
    found = run(repo)
    assert found[("warn", "api", "app/engine.py", 4)] == (
        "signature changed: build_engine(config) → build_engine(config, *, strict)"
    )


def test_debug_leftovers_and_todos_in_added_lines_only(repo):
    write(
        repo,
        "app/cli.py",
        """\
        import argparse
        import pdb
        from app.engine import build_engine

        def main():
            config = {}
            print(config)
            print(f"{config=}")
            breakpoint()
            build_engine(config)  # TODO: validate config
        """,
    )
    write(repo, "app/lib.py", "def f(value):\n    print(value)\n    return value\n")
    write(repo, "web/app.ts", "export function go() {\n  console.log('x');\n  debugger;\n}\n")
    found = {(path, line): message for (_level, kind, path, line), message in run(repo).items() if kind == "debug"}
    assert found[("app/cli.py", 2)].startswith("debugger left in")
    assert found[("app/cli.py", 8)].startswith("debug print")
    assert found[("app/cli.py", 9)].startswith("debugger left in")
    assert found[("app/cli.py", 10)].startswith("new TODO/FIXME")
    assert ("app/cli.py", 7) not in found, "printing a variable is normal output in a command-line program"
    assert found[("app/lib.py", 2)].startswith("print of a variable")
    assert found[("web/app.ts", 2)].startswith("console.log") and found[("web/app.ts", 3)].startswith("debugger")


def test_risky_files_and_missing_tests(repo):
    write(repo, "package-lock.json", '{"x": 1}\n')
    write(repo, ".env", "TOKEN=x\n")
    write(repo, ".github/workflows/ci.yml", "on: push\n")
    engine = "class Engine:\n    def start(self, speed): ...\n\ndef build_engine(config): ...\n"
    write(repo, "app/engine.py", engine + "\ndef unused_helper(): return 1\n")
    found = run(repo)
    kinds = {(level, kind, path) for (level, kind, path, _line) in found}
    assert ("warn", "dependencies", "package-lock.json") in kinds
    assert ("high", "config", ".env") in kinds and ("warn", "config", ".github/workflows/ci.yml") in kinds
    assert any(kind == "tests" and level == "warn" for level, kind, _path in kinds)


def test_json_and_unknown_base(repo, capsys):
    assert cli.main(["diffcheck", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["findings"] == []
    assert cli.main(["diffcheck", "--base", "nope"]) == 1
    assert "unknown base" in capsys.readouterr().err
