import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
release = importlib.util.module_from_spec(spec)
sys.modules["release"] = release
spec.loader.exec_module(release)

CHANGELOG = """# Changelog

## [Unreleased]

### Added

- a new thing

## [0.3.0] - 2026-10-13

- older

[Unreleased]: https://github.com/o/r/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/o/r/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/o/r/releases/tag/v0.2.0
"""


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True).stdout


def commit(path, subject, body=""):
    (path / "n.txt").write_text(subject + body)
    git(path, "add", ".")
    git(
        path,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-q",
        "-m",
        subject + ("\n\n" + body if body else ""),
    )


@pytest.fixture
def repo(tmp_path):
    files = {
        "pyproject.toml": '[project]\nname = "x"\nversion = "0.3.0"\n',
        "src/claude_toolkit/__init__.py": '"""x."""\n\n__version__ = "0.3.0"\n',
        "uv.lock": 'version = 1\n\n[[package]]\nname = "other"\nversion = "0.3.0"\n\n'
        '[[package]]\nname = "claude-toolkit"\nversion = "0.3.0"\nsource = { editable = "." }\n',
        "plugin/.claude-plugin/plugin.json": '{\n  "name": "ctk",\n  "version": "0.3.0"\n}\n',
        "docs/CHANGELOG.md": CHANGELOG,
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init")
    git(tmp_path, "tag", "v0.3.0")
    return tmp_path


@pytest.mark.parametrize(
    ("subjects", "expected"),
    [
        ([], None),
        (["docs: update", "chore: bump", "ci: x", "test: y", "refactor: z", "not conventional"], None),
        (["fix: a"], "0.3.1"),
        (["perf(map): faster", "revert: undo"], "0.3.1"),
        (["fix: a", "feat: b"], "0.4.0"),
        (["feat(relay)!: drop the old flag"], "0.4.0"),
        (["fix!: break"], "0.4.0"),
    ],
)
def test_next_version_follows_the_conventional_commits(repo, subjects, expected):
    for subject in subjects:
        commit(repo, subject)
    assert release.plan(repo)["next"] == expected


def test_a_breaking_footer_and_the_major_after_1_0():
    assert release.level_of([("feat: x", "BREAKING CHANGE: gone")])[0] == "major"
    assert release.level_of([("feat: x", "see BREAKING CHANGE: inline")])[0] == "minor", "only a footer line counts"
    assert release.bump("0.3.4", "major") == "0.4.0", "before 1.0.0 a breaking change is a minor bump"
    assert release.bump("1.2.3", "major") == "2.0.0" and release.bump("1.2.3", "minor") == "1.3.0"
    assert release.bump("1.2.3", "patch") == "1.2.4"


def test_release_commits_and_merges_do_not_count(repo):
    commit(repo, "chore: release 0.3.1")
    commit(repo, "docs: x")
    assert release.plan(repo)["next"] is None
    git(repo, "switch", "-q", "-c", "feature")
    commit(repo, "feat: from a branch")
    git(repo, "switch", "-q", "main")
    git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "merge",
        "--no-ff",
        "-m",
        "Merge pull request #1",
        "feature",
    )
    result = release.plan(repo)
    assert result["next"] == "0.4.0" and result["commits"] == ["feat: from a branch"], (
        "the commit counts, the merge does not"
    )


def test_prepare_writes_every_file_and_cuts_the_changelog(repo):
    commit(repo, "feat: x")
    changed = release.prepare(repo, "0.4.0", "2026-10-14")
    assert changed == [*(name for name, _ in release.FILES), release.CHANGELOG]
    assert release.declared(repo) == dict.fromkeys([name for name, _ in release.FILES] + [release.CHANGELOG], "0.4.0")
    lock = (repo / "uv.lock").read_text()
    assert 'name = "other"\nversion = "0.3.0"' in lock, "only the package itself changes"
    assert json.loads((repo / "plugin/.claude-plugin/plugin.json").read_text())["version"] == "0.4.0"
    text = (repo / "docs/CHANGELOG.md").read_text()
    assert "## [Unreleased]\n\n## [0.4.0] - 2026-10-14\n\n### Added\n\n- a new thing\n\n## [0.3.0]" in text
    assert (
        "[Unreleased]: https://github.com/o/r/compare/v0.4.0...HEAD\n[0.4.0]: https://github.com/o/r/compare/v0.3.0...v0.4.0\n"
        in text
    )
    assert release.notes(repo, "0.4.0") == "### Added\n\n- a new thing\n"
    assert release.notes(repo, "0.3.0") == "- older\n"
    assert release.check(repo) == []


def test_a_prepared_release_is_not_proposed_again_until_it_is_tagged(repo):
    commit(repo, "feat: x")
    release.prepare(repo, "0.4.0", "2026-10-14")
    commit(repo, "chore: release 0.4.0")
    assert release.plan(repo)["next"] is None and "on its way" in release.plan(repo)["why"]
    git(repo, "tag", "v0.4.0")
    commit(repo, "fix: later")
    assert release.plan(repo)["next"] == "0.4.1"


def test_prepare_refuses_what_would_corrupt_a_release(repo):
    with pytest.raises(release.ReleaseError, match="not newer"):
        release.prepare(repo, "0.3.0", "2026-10-14")
    with pytest.raises(release.ReleaseError, match="not a version"):
        release.prepare(repo, "1.0", "2026-10-14")
    (repo / "docs/CHANGELOG.md").write_text(CHANGELOG.replace("### Added\n\n- a new thing\n\n", ""))
    with pytest.raises(release.ReleaseError, match="empty"):
        release.prepare(repo, "0.4.0", "2026-10-14")
    assert set(release.declared(repo).values()) == {"0.3.0"}, "a refused release changes no file"


def test_disagreeing_files_block_a_release(repo):
    (repo / "pyproject.toml").write_text('[project]\nversion = "0.3.1"\n')
    assert any("src/claude_toolkit/__init__.py has 0.3.0" in problem for problem in release.check(repo))
    assert release.plan(repo)["next"] is None and "disagree" in release.plan(repo)["why"]
    assert release.main(["--root", str(repo), "check"]) == 1


def test_command_line(repo, capsys):
    commit(repo, "fix: y")
    assert release.main(["--root", str(repo), "next"]) == 0
    assert capsys.readouterr().out.strip() == "0.3.1"
    assert release.main(["--root", str(repo), "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["level"] == "patch"
    assert release.main(["--root", str(repo), "notes", "9.9.9"]) == 1
    assert release.main(["--root", str(repo), "pr", "--dry-run"]) == 0
    assert "release/0.3.1" in capsys.readouterr().out


def test_pr_refuses_a_checkout_that_is_not_at_origin_main(repo, tmp_path_factory, capsys):
    remote = tmp_path_factory.mktemp("remote")
    git(remote, "init", "-q", "--bare", "-b", "main")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    commit(repo, "feat: only here")
    assert release.main(["--root", str(repo), "pr", "--yes"]) == 1
    assert "not at origin/main" in capsys.readouterr().err
    assert not list(repo.parent.glob(f"{repo.name}-release-*")), "no worktree was created"


def test_this_repository_keeps_its_version_files_in_step():
    assert release.check(ROOT) == [], "run `make release`; do not edit versions by hand"
    versions = set(release.declared(ROOT).values())
    assert len(versions) == 1


# --- changelog fragments ---------------------------------------------------------------------------


def fragment(repo, name, text):
    path = repo / "docs" / "changelog.d" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_fragments_are_folded_into_the_sections_in_order_and_removed(repo):
    readme = fragment(repo, "README.md", "How this folder works.")
    fragment(repo, "relay.added.md", "- the relay thing")
    fragment(repo, "early.added.md", "a plain sentence\nsecond line of it")
    fragment(repo, "later.fixed.md", "- a fix")
    fragment(repo, "audit.security.md", "- a security note")
    fragment(repo, "tweak.changed.md", "- a change")
    changed = release.prepare(repo, "0.4.0", "2026-10-14")
    assert changed[-1] == "5 changelog fragment(s) folded in"
    text = (repo / "docs/CHANGELOG.md").read_text(encoding="utf-8")
    section = text[text.index("## [0.4.0]") : text.index("## [0.3.0]")]
    assert (
        section.index("### Added")
        < section.index("### Changed")
        < section.index("### Fixed")
        < section.index("### Security")
    )
    assert "- a new thing\n- a plain sentence\n  second line of it\n- the relay thing\n" in section, (
        "old entry, then by file name"
    )
    assert "### Fixed\n\n- a fix\n" in section
    assert not list((repo / "docs/changelog.d").glob("*.*.md")) and readme.exists(), "folded files go, the README stays"
    assert release.notes(repo, "0.4.0") == section.split("\n", 2)[2].strip() + "\n"


def test_a_release_can_be_made_of_fragments_alone(repo):
    (repo / "docs/CHANGELOG.md").write_text(CHANGELOG.replace("### Added\n\n- a new thing\n\n", ""), encoding="utf-8")
    fragment(repo, "only.added.md", "- the only entry")
    release.prepare(repo, "0.4.0", "2026-10-14")
    assert "## [0.4.0] - 2026-10-14\n\n### Added\n\n- the only entry\n\n## [0.3.0]" in (
        repo / "docs/CHANGELOG.md"
    ).read_text(encoding="utf-8")
    with pytest.raises(release.ReleaseError, match="empty"):
        (repo / "docs/CHANGELOG.md").write_text(
            CHANGELOG.replace("### Added\n\n- a new thing\n\n", ""), encoding="utf-8"
        )
        release.prepare(repo, "0.5.0", "2026-10-15")


def test_the_preview_shows_what_the_next_release_will_hold(repo, capsys):
    assert release.unreleased(repo) == "### Added\n\n- a new thing"
    fragment(repo, "x.fixed.md", "- fixed x")
    assert release.main(["--root", str(repo), "changelog"]) == 0
    assert capsys.readouterr().out == "### Added\n\n- a new thing\n\n### Fixed\n\n- fixed x\n"
    assert release.plan(repo)["fragments"] == 1


def test_a_misnamed_or_empty_fragment_is_reported_not_silently_dropped(repo):
    fragment(repo, "README.md", "ignored")
    fragment(repo, "good.added.md", "- ok")
    fragment(repo, "no-category.md", "- lost")
    fragment(repo, "wrong.improved.md", "- lost")
    fragment(repo, "blank.fixed.md", "  \n")
    problems = release.check(repo)
    assert any("no-category.md" in p for p in problems) and any("wrong.improved.md" in p for p in problems)
    assert any("blank.fixed.md is empty" in p for p in problems) and not any(
        "good.added" in p or "README" in p for p in problems
    )
    assert release.main(["--root", str(repo), "check"]) == 1


def test_the_pull_request_check_accepts_a_fragment():
    workflow = (ROOT / ".github" / "workflows" / "pr-checks.yml").read_text(encoding="utf-8")
    assert "docs/changelog.d/" in workflow and "docs/CHANGELOG.md" in workflow
    for category in release.CATEGORIES:
        assert category in workflow
