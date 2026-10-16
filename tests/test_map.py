import json
import subprocess
import textwrap

from claude_toolkit import cli
from claude_toolkit import map as repo_map


def write(root, name, text=""):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))
    return path


def make_repo(root):
    write(
        root,
        "app/core.py",
        """\
        class Engine:
            def start(self, speed, *, warm=False): ...
            def _internal(self): ...

        def build_engine(config): ...

        def _helper(): ...
        """,
    )
    write(
        root, "app/cli.py", "from app.core import Engine, build_engine\n\ndef main(argv=None):\n    build_engine({})\n"
    )
    write(root, "app/report.py", "from app.core import Engine\n\ndef render(engine: Engine): ...\n")
    write(
        root,
        "web/index.ts",
        """\
        export interface Options { verbose: boolean }
        export async function startServer(port: number): Promise<void> {}
        export const handler = (req, res) => {}
        """,
    )
    write(root, "tests/test_core.py", "from app.core import Engine\n\ndef test_engine():\n    Engine().start(1)\n")
    write(root, "docs/guide.md", "# Guide\nEngine usage.\n")
    write(root, "plugin/skills/one/SKILL.md", "x")
    write(root, "plugin/skills/two/SKILL.md", "x")
    write(root, "assets/logo.png", "")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_map_lists_source_symbols_and_summarises_the_rest(tmp_path):
    repo = repo_map.build(make_repo(tmp_path))
    text = repo_map.render(repo, budget=40)
    lines = text.splitlines()
    assert lines[0].startswith("map: ") and "4 source" in lines[0]
    core = next(line for line in lines if line.strip().startswith("core.py"))
    assert "class Engine(start)" in core and "build_engine(config)" in core
    assert "_helper" not in text and "_internal" not in text
    assert any("startServer(port: number)" in line and "interface" not in line for line in lines)
    assert "plugin/  (2 docs)" in text  # directories without code are rolled up
    assert "tests/  (1 tests)" in text and "docs/  (1 docs)" in text


def test_central_files_and_names_come_first(tmp_path):
    repo = repo_map.build(make_repo(tmp_path))
    scores = {entry.path: entry.score for entry in repo.files}
    assert scores["app/core.py"] > scores["app/report.py"]
    core = next(entry for entry in repo.files if entry.path == "app/core.py")
    assert core.symbols[0].name == "Engine"  # mentioned by three other files


def test_budget_is_respected_and_says_what_it_hid(tmp_path):
    root = make_repo(tmp_path)
    for index in range(30):
        write(root, f"pkg/m{index}.py", f"def f{index}(): ...\n")
    text = repo_map.render(repo_map.build(root), budget=15)
    assert len(text.splitlines()) <= 15
    assert "less-used source files not shown" in text


def test_uses_lists_definition_first_and_the_tests(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert cli.main(["map", str(root), "--uses", "Engine"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("map: Engine · 1 definition") and "[definition] class Engine:" in out[1]
    assert any("app/cli.py:1  [source]" in line for line in out)
    assert out[-1] == "tests: tests/test_core.py"
    assert cli.main(["map", str(root), "--uses", "NoSuchThing"]) == 1


def test_uses_rejects_empty_and_blank_names(tmp_path, capsys):
    root = make_repo(tmp_path)
    for name in ("", "  "):
        assert cli.main(["map", str(root), "--uses", name]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "map: --uses needs a symbol name" in captured.err


def test_without_uses_prints_the_full_map(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert cli.main(["map", str(root)]) == 0
    output = capsys.readouterr().out
    assert output.startswith("map: ")
    assert "app/" in output


def test_json_and_no_code_is_executed(tmp_path, capsys):
    root = make_repo(tmp_path)
    write(root, "app/boom.py", "raise SystemExit('executed!')\ndef safe(): ...\n")
    assert cli.main(["map", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {f["path"] for f in data["files"]} >= {"app/core.py", "app/boom.py"}


def test_other_languages():
    go = repo_map.text_symbols(
        "package x\n\nfunc (s *Server) Start(port int) error {\n}\ntype Server struct {}\n", "go"
    )
    assert [(s.name, s.kind) for s in go] == [("Start", "function"), ("Server", "type")]
    rust = repo_map.text_symbols("pub struct Engine;\npub async fn run(cfg: Config) {}\nfn private() {}\n", "rust")
    assert [s.name for s in rust] == ["Engine", "run"]
    gd = repo_map.text_symbols("extends Node\nclass_name Player\nsignal died\nfunc move(dir: Vector2):\n", "gd")
    assert [s.name for s in gd] == ["Player", "died", "move"]
