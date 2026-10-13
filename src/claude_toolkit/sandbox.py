"""``ctk sandbox``: run a command in a bubblewrap jail.

The jail sees the system read-only (``/usr``, ``/etc`` and the usual
symlinks), a private ``/tmp`` and an empty home, the target directory
read-write at its real path, and nothing else of the user's files. There is no
network unless ``--net`` is given. Memory, CPU and process limits come from a
systemd user scope (cgroups); without a user session only the wall-clock
timeout applies, and the command says so. The timeout stops the whole tree.

It never falls back to running the command unsandboxed.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .common import detect_host

EXIT_TIMEOUT = 124
DEFAULTS = {"memory": None, "tmp-size": None, "cpus": 2.0, "pids": 512, "timeout": 600.0}
MAX_DEFAULT_MEMORY = 4 * 1024**3
MAX_DEFAULT_TMP = 1024**3
SMALL_TMPFS = 64 * 1024**2
SYSTEM_DIRS = ("/usr", "/etc", "/opt")
TOP_LEVEL_LINKS = ("/bin", "/sbin", "/lib", "/lib64", "/lib32")
KEPT_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ", "NO_COLOR", "FORCE_COLOR", "COLORTERM")
# Toolchains installed under the home directory, mounted read-only so projects
# still build. Only binaries and installed versions: never credential files
# such as ~/.cargo/credentials.toml, ~/.npmrc or ~/.config.
TOOLCHAIN_DIRS = (
    ".local/bin",
    ".local/share/uv/python",
    ".local/share/uv/tools",
    ".cargo/bin",
    ".rustup/toolchains",
    ".nvm/versions",
    ".local/share/fnm",
    ".volta/tools",
    ".bun/bin",
    ".deno/bin",
    "go/bin",
    ".pyenv/versions",
    ".local/share/mise/installs",
    ".sdkman/candidates",
)


class SandboxError(Exception):
    """The sandbox cannot be set up; the command was not run."""


@dataclass
class Profile:
    target: Path
    network: bool = False
    read_only_target: bool = False
    toolchains: bool = True
    extra_ro: list[Path] = field(default_factory=list)
    extra_rw: list[Path] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    memory: str = ""  # empty: default_memory()
    tmp_size: str = ""  # empty: default_tmp_size()
    cpus: float = DEFAULTS["cpus"]
    pids: int = DEFAULTS["pids"]
    timeout: float = DEFAULTS["timeout"]


def parse_memory(text: str) -> int:
    """Bytes in ``512M``, ``4G``, ``1.5G`` or a plain number."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMGT]?)i?B?\s*", text, re.IGNORECASE)
    if not match:
        raise ValueError(f"memory must look like 512M or 4G, got {text!r}")
    unit = match.group(2).upper()
    return int(float(match.group(1)) * 1024 ** ("KMGT".index(unit) + 1 if unit else 0))


def total_memory() -> int | None:
    """Physical memory in bytes, from /proc/meminfo."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _size(nbytes: int) -> str:
    return f"{nbytes // 1024**3}G" if nbytes % 1024**3 == 0 else f"{nbytes // 1024**2}M"


def default_memory(total: int | None = None) -> str:
    """Half the machine's RAM, at most 4G and at least 256M, so a small machine keeps room for itself."""
    total = total if total is not None else total_memory()
    if not total:
        return _size(MAX_DEFAULT_MEMORY)
    return _size(max(256 * 1024**2, min(MAX_DEFAULT_MEMORY, total // 2 // 1024**2 * 1024**2)))


def default_tmp_size(total: int | None = None) -> str:
    """tmpfs lives in RAM: an eighth of it, at most 1G and at least 128M, for /tmp and the home."""
    total = total if total is not None else total_memory()
    if not total:
        return _size(MAX_DEFAULT_TMP)
    return _size(max(128 * 1024**2, min(MAX_DEFAULT_TMP, total // 8 // 1024**2 * 1024**2)))


def bwrap_supports_size() -> bool:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return False
    try:
        done = subprocess.run([bwrap, "--help"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "--size" in done.stdout + done.stderr


def _bind_args(flag: str, path: Path) -> list[str]:
    return [flag, str(path), str(path)]


def bwrap_args(profile: Profile, home: Path | None = None, *, sized: bool = True) -> list[str]:
    """The bubblewrap arguments for ``profile`` (without the command).

    With ``sized``, every tmpfs gets a size cap: tmpfs pages live in RAM, and
    without a cgroup nothing else would bound them.
    """
    home = home or Path.home()
    tmp_bytes = parse_memory(profile.tmp_size or default_tmp_size())

    def tmpfs(path: str, nbytes: int) -> list[str]:
        return (["--size", str(nbytes)] if sized else []) + ["--tmpfs", path]

    args = ["--unshare-all", "--die-with-parent", "--new-session", "--hostname", "sandbox", "--cap-drop", "ALL"]
    if profile.network:
        args.append("--share-net")
    for directory in SYSTEM_DIRS:
        if Path(directory).is_dir():
            args += _bind_args("--ro-bind", Path(directory))
    for link in TOP_LEVEL_LINKS:
        path = Path(link)
        if path.is_symlink():
            args += ["--symlink", os.readlink(path), link]
        elif path.is_dir():
            args += _bind_args("--ro-bind", path)
    args += ["--proc", "/proc", "--dev", "/dev"]
    args += [*tmpfs("/tmp", tmp_bytes), *tmpfs("/run", SMALL_TMPFS), *tmpfs("/var", SMALL_TMPFS)]
    if profile.network and Path("/run/systemd/resolve").is_dir():
        args += _bind_args("--ro-bind", Path("/run/systemd/resolve"))  # /etc/resolv.conf often points here
    args += tmpfs(str(home), tmp_bytes)
    if profile.toolchains:
        for relative in TOOLCHAIN_DIRS:
            path = home / relative
            if path.is_dir():
                args += _bind_args("--ro-bind", path)
    for path in profile.extra_ro:
        args += _bind_args("--ro-bind", path)
    for path in profile.extra_rw:
        args += _bind_args("--bind", path)
    args += _bind_args("--ro-bind" if profile.read_only_target else "--bind", profile.target)
    args += ["--clearenv"]
    env = {name: os.environ[name] for name in KEPT_ENV if name in os.environ}
    env.update({"HOME": str(home), "TMPDIR": "/tmp", "CTK_SANDBOX": "1", **profile.env})
    for name, value in env.items():
        args += ["--setenv", name, value]
    return args


def systemd_scope_available() -> bool:
    if not shutil.which("systemd-run"):
        return False
    try:
        done = subprocess.run(
            ["systemd-run", "--user", "--scope", "--quiet", "--collect", "true"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def limit_prefix(profile: Profile, scope: bool) -> list[str]:
    """Resource limits around bwrap through a systemd user scope (cgroups).

    There is deliberately no rlimit fallback: RLIMIT_AS breaks runtimes that
    reserve large address ranges (V8, the JVM) and RLIMIT_NPROC counts every
    process of the user, not just the sandbox's.
    """
    if not scope:
        return []
    memory = parse_memory(profile.memory or default_memory())
    return [
        "systemd-run", "--user", "--scope", "--quiet", "--collect",
        "-p", f"MemoryMax={memory}", "-p", "MemorySwapMax=0",
        "-p", f"CPUQuota={round(profile.cpus * 100)}%", "-p", f"TasksMax={profile.pids}",
    ]  # fmt: skip


def build_command(profile: Profile, command: list[str], cwd: Path, *, scope: bool) -> list[str]:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise SandboxError(f"bubblewrap (bwrap) is not installed: {install_hint()}")
    workdir = cwd if _inside(cwd, profile.target) else profile.target
    args = bwrap_args(profile, sized=bwrap_supports_size())
    return [*limit_prefix(profile, scope), bwrap, *args, "--chdir", str(workdir), "--", *command]


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def install_hint() -> str:
    manager = detect_host().package_manager
    commands = {
        "pacman": "sudo pacman -S --needed bubblewrap",
        "apt": "sudo apt install bubblewrap",
        "dnf": "sudo dnf install bubblewrap",
        "zypper": "sudo zypper install bubblewrap",
    }
    return commands.get(manager or "", "install bubblewrap with your package manager")


def preflight() -> None:
    """Fail early, with the reason, when the kernel refuses unprivileged namespaces."""
    if platform.system() != "Linux":
        raise SandboxError("ctk sandbox needs Linux (bubblewrap and user namespaces)")
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise SandboxError(f"bubblewrap (bwrap) is not installed: {install_hint()}")
    done = subprocess.run(
        [bwrap, "--unshare-all", "--ro-bind", "/", "/", "true"], capture_output=True, text=True, timeout=10, check=False
    )
    if done.returncode != 0:
        detail = done.stderr.strip().splitlines()[-1] if done.stderr.strip() else f"exit {done.returncode}"
        hint = ""
        if Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns").exists():
            hint = (
                " (AppArmor restricts unprivileged user namespaces: "
                "`sudo sysctl kernel.apparmor_restrict_unprivileged_userns=0`, or an AppArmor profile for bwrap)"
            )
        raise SandboxError(f"bubblewrap cannot create a sandbox here: {detail}{hint}")


@dataclass
class Result:
    exit_code: int
    timed_out: bool = False
    seconds: float = 0.0


def execute(full_command: list[str], timeout: float) -> Result:
    """Run with inherited stdio; stop the whole tree on timeout."""
    started = time.monotonic()
    process = subprocess.Popen(full_command, start_new_session=True)
    try:
        code = process.wait(timeout=timeout)
        return Result(code, False, time.monotonic() - started)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        return Result(EXIT_TIMEOUT, True, time.monotonic() - started)
    except KeyboardInterrupt:
        _kill_tree(process)
        raise


def _kill_tree(process: subprocess.Popen) -> None:
    for sig, wait in ((signal.SIGTERM, 3), (signal.SIGKILL, 5)):
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def _config(target: Path) -> dict:
    """The ``[sandbox]`` table of the nearest .claude-toolkit.toml."""
    from .hooks.base import _read_toml, find_project_config

    path = find_project_config(target)
    table = _read_toml(path).get("sandbox", {}) if path else {}
    return table if isinstance(table, dict) else {}


def profile_from_args(args) -> Profile:
    target = Path(args.dir).expanduser().resolve()
    if not target.is_dir():
        raise SandboxError(f"not a directory: {target}")
    config = _config(target)
    home = Path.home()
    if target in (home, Path("/")) or _inside(home, target):
        raise SandboxError(f"refusing to mount {target} into the sandbox: it contains the whole home directory")

    def pick(name: str, cast):
        value = getattr(args, name.replace("-", "_"))
        if value is not None:
            return value
        configured = config.get(name, DEFAULTS[name])
        return cast(configured) if configured is not None else ""

    env = {}
    for item in args.env or []:
        name, sep, value = item.partition("=")
        if not sep:
            value = os.environ.get(name, "")
        env[name] = value
    return Profile(
        target=target,
        network=args.net or bool(config.get("net", False)),
        read_only_target=args.read_only,
        toolchains=not args.no_toolchains,
        extra_ro=[Path(p).expanduser().resolve() for p in [*(config.get("ro") or []), *(args.ro or [])]],
        extra_rw=[Path(p).expanduser().resolve() for p in args.rw or []],
        env=env,
        memory=str(pick("memory", str)),
        tmp_size=str(pick("tmp-size", str)),
        cpus=pick("cpus", float),
        pids=pick("pids", int),
        timeout=pick("timeout", float),
    )


def describe(profile: Profile, scope: bool) -> str:
    memory = profile.memory or default_memory()
    if scope:
        limits = f"memory {memory}, {profile.cpus:g} CPU, {profile.pids} processes, {profile.timeout:g}s"
    else:
        limits = f"{profile.timeout:g}s timeout only (no systemd user session for memory/CPU/process limits)"
    lines = [
        f"sandbox: {profile.target} ({'read-only' if profile.read_only_target else 'read-write'})",
        f"  network: {'on' if profile.network else 'off'}",
        f"  limits: {limits}",
        "  visible: /usr /etc /opt read-only, empty home and /tmp"
        + (", toolchains read-only" if profile.toolchains else ""),
        f"  tmpfs (RAM): /tmp and home up to {profile.tmp_size or default_tmp_size()} each, /run and /var 64M",
    ]
    lines += [f"  extra read-only: {path}" for path in profile.extra_ro]
    lines += [f"  extra read-write: {path}" for path in profile.extra_rw]
    return "\n".join(lines)


def run(args) -> int:
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        print("usage: ctk sandbox [options] -- <command> [args...]", file=sys.stderr)
        return 2
    try:
        profile = profile_from_args(args)
        parse_memory(profile.memory or default_memory())
        parse_memory(profile.tmp_size or default_tmp_size())
        preflight()
        scope = systemd_scope_available()
        full = build_command(profile, command, Path.cwd().resolve(), scope=scope)
    except (SandboxError, ValueError) as error:
        print(f"sandbox: {error}", file=sys.stderr)
        return 1
    if not scope and not args.dry_run:
        print("sandbox: no systemd user session; memory, CPU and process limits are not applied", file=sys.stderr)
    if args.dry_run:
        print(describe(profile, scope))
        print("  command: " + " ".join(_quote(part) for part in full))
        return 0
    result = execute(full, profile.timeout)
    if result.timed_out:
        print(f"sandbox: stopped after {profile.timeout:g}s (timeout)", file=sys.stderr)
    elif killed_by_limit(result.exit_code, scope):
        memory = profile.memory or default_memory()
        print(f"sandbox: killed by a signal; likely the memory limit of {memory}", file=sys.stderr)
    code = result.exit_code
    return 128 - code if code < 0 else code


def killed_by_limit(exit_code: int, scope: bool) -> bool:
    """Whether a run ended the way the memory limit ends it.

    The kernel's OOM killer sends SIGKILL; when the systemd scope stops after
    an out-of-memory kill, the rest of the tree gets SIGTERM first. Without a
    scope there is no memory limit, so only SIGKILL is attributed to memory.
    """
    killed = {-signal.SIGKILL, 128 + signal.SIGKILL}
    if scope:
        killed |= {-signal.SIGTERM, 128 + signal.SIGTERM}
    return exit_code in killed


def _quote(text: str) -> str:
    return text if re.fullmatch(r"[\w@%+=:,./-]+", text) else "'" + text.replace("'", "'\\''") + "'"
