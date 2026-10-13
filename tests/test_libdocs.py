import json
import textwrap

import pytest

from claude_toolkit import cli


def write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))
    return path


@pytest.fixture
def python_project(tmp_path):
    project = tmp_path / "app"
    write(project / "pyproject.toml", '[project]\nname = "app"\ndependencies = ["requests>=2.31,<3", "PyYAML"]\n')
    site = project / ".venv" / "lib" / "python3.12" / "site-packages"
    write(
        site / "requests-2.32.3.dist-info" / "METADATA",
        """\
        Metadata-Version: 2.1
        Name: requests
        Version: 2.32.3
        Summary: Python HTTP for Humans.
        Home-page: https://requests.readthedocs.io

        # Requests
        ## Installation
        ## Usage
        """,
    )
    write(site / "requests-2.32.3.dist-info" / "top_level.txt", "requests\n")
    write(
        site / "requests" / "__init__.py",
        '''\
        """Requests."""
        from .api import get, post
        from .sessions import Session
        from . import _internal
        __version__ = "2.32.3"
        def _private(): ...
        ''',
    )
    write(
        site / "requests" / "api.py",
        '''\
        def get(url, params=None, **kwargs):
            """Sends a GET request.

            More details here.
            """
        def post(url, data=None, json=None, **kwargs): ...
        ''',
    )
    write(
        site / "requests" / "sessions.py",
        '''\
        class Session(SessionRedirectMixin):
            """A Requests session."""
            def __init__(self): ...
            def get(self, url: str, **kwargs) -> "Response":
                """Sends a GET request. Returns :class:`Response` object."""
            def _hidden(self): ...
        ''',
    )
    write(site / "PyYAML-6.0.2.dist-info" / "METADATA", "Name: PyYAML\nVersion: 6.0.2\n\n")
    write(site / "PyYAML-6.0.2.dist-info" / "top_level.txt", "_yaml\nyaml\n")
    write(
        site / "yaml" / "__init__.py",
        "__all__ = ['safe_load']\ndef safe_load(stream): ...\ndef load(stream, Loader): ...\n",
    )
    return project


def test_python_summary_shows_version_constraint_readme_and_api(python_project, capsys):
    assert cli.main(["libdocs", "requests", str(python_project)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("libdocs: requests 2.32.3 (python) · ")
    assert "declared: requests>=2.31,<3 in" in out and "docs: https://requests.readthedocs.io" in out
    assert "sections: Requests · Installation · Usage" in out
    assert "from .api import get, post" in out and "from .sessions import Session" in out
    assert "_internal" not in out and "_private" not in out and "__version__" not in out


def test_python_finds_by_import_name_and_respects_all(python_project, capsys):
    assert cli.main(["libdocs", "yaml", str(python_project)]) == 0
    out = capsys.readouterr().out
    assert "libdocs: PyYAML 6.0.2" in out and "declared: PyYAML" in out
    assert "def safe_load(stream)" in out and "def load(" not in out


def test_python_find_symbol_gives_signature_and_doc(python_project, capsys):
    assert cli.main(["libdocs", "requests", str(python_project), "--find", "Session.get"]) == 0
    out = capsys.readouterr().out
    assert "sessions.py:4" in out
    assert "def Session.get(self, url: str, **kwargs) -> 'Response'" in out and "Returns :class:`Response`" in out
    assert cli.main(["libdocs", "requests", str(python_project), "--find", "get"]) == 0
    first = capsys.readouterr().out
    assert "api.py:1" in first and "Sends a GET request." in first and "More details" not in first


def test_readme_from_metadata(python_project, capsys):
    assert cli.main(["libdocs", "requests", str(python_project), "--readme"]) == 0
    assert "## Usage" in capsys.readouterr().out


def test_node_types_declared_and_find(tmp_path, capsys):
    project = tmp_path / "web"
    write(project / "package.json", json.dumps({"dependencies": {"@acme/client": "^1.2.0"}}))
    package = project / "node_modules" / "@acme" / "client"
    write(package / "package.json", json.dumps(
        {"name": "@acme/client", "version": "1.4.0", "description": "Acme client", "types": "dist/index.d.ts"}
    ))  # fmt: skip
    write(package / "README.md", "# Acme\n## Setup\n")
    write(
        package / "dist" / "index.d.ts",
        """\
        export interface ClientOptions<
          T = unknown
        > {
          baseUrl: string;
        }
        export declare function createClient(options: ClientOptions): Client;
        export type {
          Client, // the main type
          Plugin,
        } from './types';
        declare const VERSION: string;
        """,
    )
    assert cli.main(["libdocs", "@acme/client", str(project)]) == 0
    out = capsys.readouterr().out
    assert "libdocs: @acme/client 1.4.0 (node)" in out and "declared: @acme/client@^1.2.0" in out
    assert "export declare function createClient(options: ClientOptions): Client;" in out
    assert "export type { Client, Plugin, } from './types';" in out and "declare const VERSION" in out
    assert cli.main(["libdocs", "@acme/client", str(project), "--find", "ClientOptions"]) == 0
    found = capsys.readouterr().out
    assert "index.d.ts:1" in found and "baseUrl: string;" in found


def test_node_falls_back_to_definitely_typed(tmp_path, capsys):
    project = tmp_path / "web"
    write(project / "node_modules" / "lodash" / "package.json", json.dumps({"version": "4.17.21"}))
    write(project / "node_modules" / "@types" / "lodash" / "package.json", json.dumps({"version": "4.17.7"}))
    write(
        project / "node_modules" / "@types" / "lodash" / "index.d.ts",
        "export declare function chunk(a: any[]): any[][];\n",
    )
    assert cli.main(["libdocs", "lodash", str(project)]) == 0
    out = capsys.readouterr().out
    assert "note: types from @types/lodash 4.17.7" in out and "function chunk" in out


def test_rust_from_lock_and_registry(tmp_path, monkeypatch, capsys):
    project = tmp_path / "crate"
    write(project / "Cargo.toml", '[dependencies]\nserde = { version = "1", features = ["derive"] }\n')
    write(project / "Cargo.lock", '[[package]]\nname = "serde"\nversion = "1.0.210"\nsource = "registry"\n')
    cargo = tmp_path / "cargo"
    source = cargo / "registry" / "src" / "index.crates.io-x" / "serde-1.0.210"
    write(source / "Cargo.toml", '[package]\nname = "serde"\ndescription = "A serialization framework"\n')
    write(
        source / "src" / "lib.rs", "pub mod de;\npub trait Serialize {\n    fn serialize(&self);\n}\nfn private() {}\n"
    )
    monkeypatch.setenv("CARGO_HOME", str(cargo))
    assert cli.main(["libdocs", "serde", str(project)]) == 0
    out = capsys.readouterr().out
    assert "libdocs: serde 1.0.210 (rust)" in out and 'declared: serde = { version = "1"' in out
    assert "pub trait Serialize" in out and "private" not in out
    assert cli.main(["libdocs", "serde", str(project), "--find", "Serialize"]) == 0
    assert "fn serialize(&self);" in capsys.readouterr().out


def test_go_from_go_mod_and_module_cache(tmp_path, monkeypatch, capsys):
    project = tmp_path / "svc"
    write(project / "go.mod", "module x\n\nrequire (\n\tgithub.com/BurntSushi/toml v1.4.0\n)\n")
    cache = tmp_path / "mod"
    module = cache / "github.com" / "!burnt!sushi" / "toml@v1.4.0"
    decode = "package toml\n\n// Decode parses TOML.\nfunc Decode(data string, v any) (MetaData, error) {\n"
    write(module / "decode.go", decode + "\treturn MetaData{}, nil\n}\nfunc helper() {}\n")
    write(module / "decode_test.go", "package toml\nfunc TestX() {}\n")
    monkeypatch.setenv("GOMODCACHE", str(cache))
    assert cli.main(["libdocs", "github.com/BurntSushi/toml", str(project)]) == 0
    out = capsys.readouterr().out
    assert "libdocs: github.com/BurntSushi/toml v1.4.0 (go)" in out
    assert "func Decode(data string, v any) (MetaData, error)" in out and "helper" not in out and "TestX" not in out
    assert cli.main(["libdocs", "github.com/BurntSushi/toml", str(project), "--find", "Decode"]) == 0
    assert "// Decode parses TOML." in capsys.readouterr().out


def test_missing_package_and_json(python_project, capsys):
    assert cli.main(["libdocs", "nope", str(python_project), "--ecosystem", "python"]) == 1
    assert "nope is not installed" in capsys.readouterr().err
    assert cli.main(["libdocs", "requests", str(python_project), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["version"] == "2.32.3" and "def get(url, params=None, **kwargs)" not in data["api"]


def test_never_imports_the_package(python_project, capsys):
    trap = python_project / ".venv" / "lib" / "python3.12" / "site-packages" / "requests" / "__init__.py"
    trap.write_text(trap.read_text() + "raise SystemExit('executed!')\n")
    assert cli.main(["libdocs", "requests", str(python_project)]) == 0
    assert "executed!" not in capsys.readouterr().out


def test_broken_package_json_is_reported_not_a_crash(tmp_path, capsys):
    project = tmp_path / "web"
    write(project / "node_modules" / "broken" / "package.json", "{ not json")
    assert cli.main(["libdocs", "broken", str(project), "--ecosystem", "node"]) == 0
    assert "unreadable or not valid JSON" in capsys.readouterr().out
