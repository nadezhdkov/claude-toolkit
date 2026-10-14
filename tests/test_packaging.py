import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
READ_ME = "tool.hatch.metadata.hooks.fancy-pypi-readme"


def readme_hook() -> dict:
    return PYPROJECT["tool"]["hatch"]["metadata"]["hooks"]["fancy-pypi-readme"]


def test_pypi_readme_has_no_relative_links_or_images():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(r'src="docs/|\]\(docs/', text), "the README does use relative links, so the rewrite matters"
    for rule in readme_hook()["substitutions"]:
        text = re.sub(rule["pattern"], rule["replacement"], text)
    assert re.findall(r'src="(?!https://)[^"]+"|\]\((?!https://|#)[^)]+\)', text) == []
    assert "https://raw.githubusercontent.com/nadezhdkov/claude-toolkit/main/docs/assets/logo.jpg" in text
    assert "](https://github.com/nadezhdkov/claude-toolkit/blob/main/docs/roadmap.md)" in text


def test_metadata_matches_what_is_tested():
    project = PYPROJECT["project"]
    assert "readme" in project["dynamic"] and "readme" not in project
    assert project["dependencies"] == [], "runtime stays stdlib-only"
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    tested = re.search(r"python: \[([^\]]+)\]", ci)
    versions = re.findall(r'"(3\.\d+)"', tested.group(1))
    classified = {
        c.rsplit(" :: ", 1)[1] for c in project["classifiers"] if c.startswith("Programming Language :: Python :: 3.")
    }
    assert versions and set(versions) == classified, "classifiers list exactly the Python versions CI tests"
    assert "Typing :: Typed" not in project["classifiers"] or (ROOT / "src/claude_toolkit/py.typed").exists()


def test_source_distribution_is_anchored_to_the_root():
    include = PYPROJECT["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert include and all(item.startswith("/") for item in include), "an unanchored README.md matches every folder"


def test_env_files_are_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored and "benchmark/.env" in ignored


def test_release_workflow_publishes_only_with_trusted_publishing():
    lines = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8").splitlines()
    text = "\n".join(line for line in lines if not line.lstrip().startswith("#"))  # comments may say "no password"
    assert "id-token: write" in text and "environment:" in text and "vars.PYPI_PUBLISH" in text
    assert "password" not in text.lower() and "PYPI_TOKEN" not in text and "secrets." not in text
    publish = text[text.index("  pypi:") :]
    assert "id-token: write" in publish and "contents: write" not in publish, (
        "the job that holds the token can't write the repo"
    )
