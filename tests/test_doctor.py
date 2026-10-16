import json
import os

import pytest

from claude_toolkit import cli, doctor

UNRELEASED = doctor.Dependency("future-tool", "a tool that has not shipped yet", False, {}, shipped=False)


@pytest.fixture
def versions(monkeypatch):
    """Pretend these tool versions are installed."""
    installed: dict[str, tuple[int, int, int] | None] = {}
    monkeypatch.setattr(doctor, "installed_version", lambda tool: installed.get(tool))
    return installed


def levels(report):
    return [(f.level, f.check) for f in report.findings]


def test_node_major_mismatch_with_nvmrc_is_an_error(tmp_path, versions):
    versions["node"] = (26, 11, 1)
    (tmp_path / ".nvmrc").write_text("24.18.0\n")
    report = doctor.check_project(tmp_path)
    assert ("error", "node") in levels(report)
    assert "nvm install 24.18.0" in report.findings[0].fix


def test_node_patch_mismatch_with_nvmrc_is_only_a_warning(tmp_path, versions):
    versions["node"] = (24, 19, 0)
    (tmp_path / ".nvmrc").write_text("v24.18.0")
    assert levels(doctor.check_project(tmp_path)) == [("warn", "node")]


def test_engines_range_and_package_manager(tmp_path, versions):
    versions.update(node=(24, 12, 0), npm=(11, 6, 2))
    (tmp_path / "package.json").write_text(
        json.dumps({"engines": {"node": ">=22.19 <23 || ^24.11"}, "packageManager": "npm@11.6.2"})
    )
    assert levels(doctor.check_project(tmp_path)) == [("ok", "node"), ("ok", "npm")]


def test_engines_hyphen_range(tmp_path, versions):
    versions["node"] = (20, 10, 0)
    (tmp_path / "package.json").write_text(json.dumps({"engines": {"node": "18 - 20"}}))
    assert levels(doctor.check_project(tmp_path)) == [("ok", "node")]


def test_missing_node_modules_with_lockfile(tmp_path, versions):
    versions["node"] = (24, 0, 0)
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "package-lock.json").write_text("{}")
    finding = next(f for f in doctor.check_project(tmp_path).findings if f.check == "node_modules")
    assert finding.level == "error" and finding.fix == "npm ci"


def test_stale_node_modules(tmp_path, versions):
    versions["node"] = (24, 0, 0)
    (tmp_path / "package.json").write_text("{}")
    marker = tmp_path / "node_modules" / ".package-lock.json"
    marker.parent.mkdir()
    marker.write_text("{}")
    lock = tmp_path / "package-lock.json"
    lock.write_text("{}")
    os.utime(marker, (1_000, 1_000))
    finding = next(f for f in doctor.check_project(tmp_path).findings if f.check == "node_modules")
    assert finding.level == "warn"


def test_python_requires_and_missing_venv(tmp_path, versions, monkeypatch):
    versions["python"] = (3, 10, 4)
    monkeypatch.setattr(doctor, "which", lambda name: None)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nrequires-python = ">=3.11"\n')
    (tmp_path / "uv.lock").write_text("")
    found = levels(doctor.check_project(tmp_path))
    assert ("error", "python") in found and ("error", "uv") in found


def test_go_minimum_version(tmp_path, versions):
    versions["go"] = (1, 21, 0)
    (tmp_path / "go.mod").write_text("module x\n\ngo 1.22\n")
    assert levels(doctor.check_project(tmp_path)) == [("error", "go")]


def test_tool_versions(tmp_path, versions):
    versions.update(node=(20, 1, 0), python=(3, 12, 2))
    (tmp_path / ".tool-versions").write_text("nodejs 22.1.0\npython 3.12  # comment\nunknown 1.0\n")
    assert levels(doctor.check_project(tmp_path)) == [("warn", "node")]


def test_project_without_pins_is_ok(tmp_path, versions):
    report = doctor.check_project(tmp_path)
    assert report.findings == []
    assert doctor.render(report).endswith("ok (no toolchain pins found)")


@pytest.mark.parametrize("path_kind", ["missing", "file"])
def test_doctor_rejects_non_directories(tmp_path, capsys, path_kind):
    path = tmp_path / "missing" if path_kind == "missing" else tmp_path / "some-file.txt"
    if path_kind == "file":
        path.write_text("not a directory")

    assert cli.main(["doctor", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"doctor: not a directory: {path.resolve()}" in captured.err


def test_toolkit_check_marks_required_and_optional(monkeypatch, versions):
    versions["python"] = (3, 12, 0)
    missing = ("uv", "ffmpeg", "gh", "bwrap", "future-tool")
    monkeypatch.setattr(doctor, "TOOLKIT_DEPENDENCIES", (*doctor.TOOLKIT_DEPENDENCIES, UNRELEASED))
    monkeypatch.setattr(doctor, "which", lambda name: None if name in missing else f"/usr/bin/{name}")
    report = doctor.check_toolkit(doctor.Host("linux", "arch"))
    by_check = {f.check: f for f in report.findings}
    assert by_check["uv"].level == "error" and "pacman" in by_check["uv"].fix
    assert by_check["gh"].level == "warn"
    assert by_check["ffmpeg"].level == "warn"
    assert by_check["bwrap"].level == "warn"
    assert "future-tool" not in by_check, "dependencies of unreleased tools stay silent"
    assert report.errors == 1


def test_toolkit_check_on_windows_uses_winget_and_skips_linux_tools(monkeypatch, versions):
    versions["python"] = (3, 12, 0)
    monkeypatch.setattr(doctor, "which", lambda name: None if name in ("gh", "bwrap", "Xvfb") else f"C:/bin/{name}")
    report = doctor.check_toolkit(doctor.Host("windows", "windows"))
    by_check = {f.check: f for f in report.findings}
    assert by_check["gh"].fix == "winget install --id GitHub.cli -e"
    assert "bwrap" not in by_check and "Xvfb" not in by_check, "Linux-only tools are not missing on Windows"
