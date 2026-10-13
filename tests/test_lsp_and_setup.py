import json
import subprocess
from pathlib import Path

import pytest

from claude_toolkit import cli, lsp, setup
from claude_toolkit.common import EXIT_NEEDS_CONFIRMATION


def make_project(root, files):
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    return root


def test_detect_languages_ignores_vendored_dirs_and_small_counts(tmp_path):
    make_project(
        tmp_path, ["a.py", "b.py", "c.py", "node_modules/x.ts", "node_modules/y.ts", "node_modules/z.ts", "one.go"]
    )
    detected = {server.language: n for server, n in lsp.detect_languages(tmp_path)}
    assert detected == {"Python": 3}


def test_detect_languages_uses_git_when_available(tmp_path):
    make_project(tmp_path, ["a.ts", "b.ts", "c.tsx", "ignored/d.ts"])
    (tmp_path / ".gitignore").write_text("ignored/\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    detected = {server.language: n for server, n in lsp.detect_languages(tmp_path)}
    assert detected == {"TypeScript/JavaScript": 3}


def test_installed_plugins_respects_disabled_entries(tmp_path):
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"pyright-lsp@claude-plugins-official": [], "gopls-lsp@claude-plugins-official": []}})
    )
    (tmp_path / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"gopls-lsp@claude-plugins-official": False}})
    )
    assert lsp.installed_plugins(tmp_path) == {"pyright-lsp"}


def test_install_hint_prefers_the_host_package_manager(monkeypatch):
    monkeypatch.setattr(lsp, "which", lambda name: None)
    rust = next(s for s in lsp.SERVERS if s.plugin == "rust-analyzer-lsp")
    assert rust.install_command(lsp.Host("linux", "arch")).startswith("sudo pacman")
    assert rust.install_command(lsp.Host("linux", "unknown")) == "rustup component add rust-analyzer"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "claude_home", lambda: tmp_path)
    monkeypatch.setattr(setup, "TOOLKIT_DEPENDENCIES", ())
    monkeypatch.setattr(setup, "claude_cli", lambda: None)
    return tmp_path


def test_snippet_insert_is_idempotent_and_reversible():
    original = "# My rules\n\nBe nice.\n"
    once = setup.with_snippet(original)
    assert once.startswith(original.rstrip("\n")) and setup.START in once
    assert setup.with_snippet(once) == once
    assert setup.strip_snippet(once) == original


def test_setup_writes_with_backup_and_uninstall_restores(home, capsys):
    (home / "CLAUDE.md").write_text("# Existing\n")
    assert setup.run(assume_yes=True, dry_run=False, uninstall=False) == 0
    assert setup.START in (home / "CLAUDE.md").read_text()
    assert len(list((home / "backups" / "claude-toolkit").iterdir())) == 1
    assert setup.run(assume_yes=True, dry_run=False, uninstall=False) == 0
    assert "nothing to do" in capsys.readouterr().out
    assert setup.run(assume_yes=True, dry_run=False, uninstall=True) == 0
    assert (home / "CLAUDE.md").read_text() == "# Existing\n"


def test_setup_dry_run_changes_nothing(home):
    assert setup.run(assume_yes=False, dry_run=True, uninstall=False) == 0
    assert not (home / "CLAUDE.md").exists()


def test_without_a_terminal_changes_need_explicit_yes(home, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["setup"]) == EXIT_NEEDS_CONFIRMATION
    assert not (home / "CLAUDE.md").exists()
    assert "rerun with --yes" in capsys.readouterr().err


def test_bare_ctk_prints_an_overview(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("claude-toolkit ") and "\x1b" not in out
    assert all(name in out for name in ("doctor", "runq", "lsp", "sessions", "setup"))


def test_setup_installs_the_plugin_once_and_uninstall_removes_it(home, monkeypatch):
    calls = []
    monkeypatch.setattr(setup, "claude_cli", lambda: "/usr/bin/claude")
    monkeypatch.setattr(setup, "_claude", lambda *args: calls.append(args) or "ok")
    steps = setup.plugin_steps()
    assert len(steps) == 1 and "install the ctk plugin" in steps[0].description
    steps[0].apply()
    assert calls == [("plugin", "marketplace", "add", setup.marketplace_source()), ("plugin", "install", "ctk@ctk")]

    (home / "plugins").mkdir()
    (home / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": {"ctk@ctk": []}}))
    (home / "plugins" / "known_marketplaces.json").write_text(json.dumps({"ctk": {}}))
    assert setup.plugin_steps() == []
    calls.clear()
    for step in setup.plugin_steps(uninstall=True):
        step.apply()
    assert calls == [("plugin", "uninstall", "ctk@ctk"), ("plugin", "marketplace", "remove", "ctk")]


def test_marketplace_source_is_this_checkout():
    source = Path(setup.marketplace_source())
    assert (source / ".claude-plugin" / "marketplace.json").is_file()
