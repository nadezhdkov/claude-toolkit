import os
from pathlib import Path

import pytest
from conftest import linux_only

from claude_toolkit import cli, sandbox


def args_for(profile: sandbox.Profile, home: Path) -> list[str]:
    return sandbox.bwrap_args(profile, home=home)


def pairs(args: list[str], flag: str) -> list[str]:
    return [args[i + 1] for i, value in enumerate(args) if value == flag]


@pytest.fixture
def fake_home(tmp_path):
    home = tmp_path / "home"
    for path in (".local/bin", ".cargo/bin", ".ssh", ".config/gh", ".aws"):
        (home / path).mkdir(parents=True)
    (home / ".cargo" / "credentials.toml").write_text("token")
    (home / ".npmrc").write_text("//registry:_authToken=x")
    return home


# --- profile and arguments --------------------------------------------------------------


def test_memory_sizes():
    assert sandbox.parse_memory("512M") == 512 * 1024**2
    assert sandbox.parse_memory("1.5G") == int(1.5 * 1024**3)
    assert sandbox.parse_memory("2048") == 2048
    with pytest.raises(ValueError):
        sandbox.parse_memory("lots")


def test_no_network_and_an_empty_home_by_default(tmp_path, fake_home):
    target = tmp_path / "project"
    target.mkdir()
    args = args_for(sandbox.Profile(target), fake_home)
    assert "--unshare-all" in args and "--share-net" not in args
    assert "--cap-drop" in args and "--die-with-parent" in args
    assert pairs(args, "--tmpfs").index(str(fake_home)) >= 0
    # The target is bound after the home and /tmp tmpfs, so it stays visible under them.
    assert args.index(str(target)) > args.index(str(fake_home))
    assert pairs(args, "--bind") == [str(target)]
    assert "--share-net" in args_for(sandbox.Profile(target, network=True), fake_home)


def test_only_toolchain_binaries_are_mounted_never_credentials(tmp_path, fake_home):
    target = tmp_path / "project"
    target.mkdir()
    mounted = pairs(args_for(sandbox.Profile(target), fake_home), "--ro-bind")
    assert str(fake_home / ".local/bin") in mounted and str(fake_home / ".cargo/bin") in mounted
    for secret in (".ssh", ".config/gh", ".aws", ".cargo", ".npmrc"):
        assert str(fake_home / secret) not in mounted
    assert not any(str(fake_home / ".local/bin") == m for m in pairs(
        args_for(sandbox.Profile(target, toolchains=False), fake_home), "--ro-bind"
    ))  # fmt: skip


def test_environment_is_cleared_except_what_is_passed(tmp_path, fake_home, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    target = tmp_path / "p"
    target.mkdir()
    args = args_for(sandbox.Profile(target, env={"CI": "1"}), fake_home)
    assert "--clearenv" in args
    names = pairs(args, "--setenv")
    assert "GITHUB_TOKEN" not in names and {"PATH", "HOME", "CI", "CTK_SANDBOX"} <= set(names)


def test_limits_use_a_systemd_scope_or_nothing(tmp_path):
    profile = sandbox.Profile(tmp_path, memory="1G", cpus=1.5, pids=64)
    prefix = sandbox.limit_prefix(profile, scope=True)
    assert prefix[:3] == ["systemd-run", "--user", "--scope"]
    assert f"MemoryMax={1024**3}" in prefix and "CPUQuota=150%" in prefix and "TasksMax=64" in prefix
    assert sandbox.limit_prefix(profile, scope=False) == []


def test_refuses_to_mount_the_whole_home(monkeypatch, capsys):
    assert cli.main(["sandbox", "--dir", str(Path.home()), "--", "true"]) == 1
    assert "whole home directory" in capsys.readouterr().err
    assert cli.main(["sandbox"]) == 2


def test_missing_bwrap_never_runs_the_command_unsandboxed(tmp_path, monkeypatch, capsys):
    marker = tmp_path / "ran"
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    code = cli.main(["sandbox", "--dir", str(tmp_path), "--", "touch", str(marker)])
    assert code == 1 and not marker.exists()
    assert "bubblewrap" in capsys.readouterr().err


def test_project_config_sets_defaults_and_flags_win(tmp_path, monkeypatch):
    (tmp_path / ".claude-toolkit.toml").write_text('[sandbox]\nmemory = "8G"\ntimeout = 30\nnet = true\n')
    parsed = cli.build_parser().parse_args(["sandbox", "--dir", str(tmp_path), "--timeout", "5", "--", "x"])
    profile = sandbox.profile_from_args(parsed)
    assert (profile.memory, profile.timeout, profile.network) == ("8G", 5.0, True)


# --- real sandbox ------------------------------------------------------------------------


def can_sandbox() -> bool:
    try:
        sandbox.preflight()
    except (sandbox.SandboxError, OSError):
        return False
    return True


real = pytest.mark.skipif(not can_sandbox(), reason="bubblewrap cannot create a sandbox here")


@real
def test_isolation_end_to_end(tmp_path, capfd):
    project = tmp_path / "project"
    project.mkdir()
    secret = Path.home() / ".ctk-sandbox-test-secret"
    script = (
        "echo hi > made.txt; "
        f"test -e {secret} && echo SECRET-VISIBLE; "
        "touch /usr/ctk-test 2>/dev/null && echo USR-WRITABLE; "
        "touch ~/in-home && echo home-writable; "
        "tail -n +3 /proc/net/dev | cut -d: -f1 | tr -d ' '; "
        "exit 7"
    )
    try:
        secret.write_text("x")
        code = cli.main(["sandbox", "--dir", str(project), "--timeout", "60", "--", "sh", "-c", script])
    finally:
        secret.unlink(missing_ok=True)
    out = capfd.readouterr().out.split()
    assert code == 7
    assert (project / "made.txt").read_text() == "hi\n"
    assert "SECRET-VISIBLE" not in out and "USR-WRITABLE" not in out
    assert "home-writable" in out and not (Path.home() / "in-home").exists()
    assert [line for line in out if line not in ("home-writable",)] == ["lo"]


@real
def test_read_only_target_and_timeout(tmp_path, capfd):
    code = cli.main(["sandbox", "--dir", str(tmp_path), "--read-only", "--", "sh", "-c", "touch x"])
    assert code != 0 and not (tmp_path / "x").exists()
    assert cli.main(["sandbox", "--dir", str(tmp_path), "--timeout", "1", "--", "sleep", "20"]) == 124
    assert "timeout" in capfd.readouterr().err


@real
def test_memory_limit_or_an_honest_warning(tmp_path, capfd):
    scope = sandbox.systemd_scope_available()
    if scope and not os.environ.get("CTK_TEST_OOM"):
        # A real OOM kill makes desktop sessions show a "low on memory" notification.
        pytest.skip("set CTK_TEST_OOM=1 to test a real out-of-memory kill")
    script = "x = b'\\x01' * (400 * 1024 * 1024); print('allocated')"
    code = cli.main(["sandbox", "--dir", str(tmp_path), "--memory", "128M", "--", "python3", "-c", script])
    captured = capfd.readouterr()
    if scope:
        # SIGKILL from the kernel, or SIGTERM when systemd stops the scope after the OOM kill.
        assert code in (137, 143) and "memory limit" in captured.err
    else:
        assert "limits are not applied" in captured.err and code == 0


def test_defaults_scale_down_on_small_machines():
    gib = 1024**3
    assert [sandbox.default_memory(n * gib) for n in (1, 2, 4, 6, 16, 64)] == ["512M", "1G", "2G", "3G", "4G", "4G"]
    assert sandbox.default_memory(256 * 1024**2) == "256M"  # never below 256M
    assert [sandbox.default_tmp_size(n * gib) for n in (1, 4, 16)] == ["128M", "512M", "1G"]


def test_every_tmpfs_is_size_capped(tmp_path, fake_home):
    target = tmp_path / "p"
    target.mkdir()
    args = args_for(sandbox.Profile(target, tmp_size="300M"), fake_home)
    sized = {args[i + 3]: int(args[i + 1]) for i, v in enumerate(args) if v == "--size"}
    assert sized == {"/tmp": 300 * 1024**2, "/run": 64 * 1024**2, "/var": 64 * 1024**2, str(fake_home): 300 * 1024**2}
    unsized = sandbox.bwrap_args(sandbox.Profile(target), home=fake_home, sized=False)
    assert "--size" not in unsized  # old bubblewrap without --size


@real
def test_tmp_is_capped_in_ram(tmp_path, capfd):
    script = "head -c 3000000 /dev/zero > /tmp/big || echo FULL"
    assert cli.main(["sandbox", "--dir", str(tmp_path), "--tmp-size", "2M", "--", "sh", "-c", script]) == 0
    assert "FULL" in capfd.readouterr().out


@linux_only
def test_limit_kills_are_recognised_by_signal():
    assert sandbox.killed_by_limit(137, scope=False) and sandbox.killed_by_limit(-9, scope=True)
    assert sandbox.killed_by_limit(143, scope=True)
    assert not sandbox.killed_by_limit(143, scope=False), "no limits without a scope: SIGTERM is something else"
    assert not sandbox.killed_by_limit(1, scope=True)
