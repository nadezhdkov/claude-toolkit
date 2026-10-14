"""Shared helpers: confirmation, host detection, version parsing and output."""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Exit code used when a change needs approval that could not be asked for.
EXIT_NEEDS_CONFIRMATION = 3


class ConfirmationRequired(Exception):
    """Raised when a change needs approval and no terminal is available."""


def confirm(question: str, *, assume_yes: bool) -> bool:
    """Ask before changing anything.

    With ``--yes`` the answer is yes. Without a terminal (for example when an
    agent runs the command) nothing is changed: the caller prints its plan and
    exits with EXIT_NEEDS_CONFIRMATION so a person can approve and rerun.
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise ConfirmationRequired(question)
    from .style import Style

    st = Style.detect()
    prompt = (
        f"{st.accent('?', bold=True)} {st.bold(question)} {st.muted('[y/N]')} " if st.enabled else f"{question} [y/N] "
    )
    try:
        answer = input(prompt).strip().lower()
    except EOFError:  # Windows reports NUL as a terminal; reading it ends at once
        raise ConfirmationRequired(question) from None
    return answer in ("y", "yes", "s", "sim")


def which(name: str) -> str | None:
    return shutil.which(name)


def run_text(args: list[str], timeout: float = 10.0) -> str | None:
    """Run a short command and return its combined output, or None if it cannot run."""
    try:
        done = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False, encoding="utf-8", errors="replace"
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (done.stdout + done.stderr).strip()


@dataclass(frozen=True)
class Host:
    system: str  # linux, darwin, windows
    distro: str  # arch, debian, fedora, suse, macos, windows, unknown

    @property
    def package_manager(self) -> str | None:
        return {
            "arch": "pacman",
            "debian": "apt",
            "fedora": "dnf",
            "macos": "brew",
            "suse": "zypper",
            "windows": "winget",
        }.get(self.distro)


def detect_host() -> Host:
    system = platform.system().lower()
    if system == "darwin":
        return Host(system, "macos")
    if system == "windows":
        return Host(system, "windows")
    if system != "linux":
        return Host(system, "unknown")
    ids: set[str] = set()
    release = Path("/etc/os-release")
    if release.exists():
        for line in release.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition("=")
            if key in ("ID", "ID_LIKE"):
                ids.update(value.strip().strip('"').lower().split())
    for family, names in (
        ("arch", {"arch", "cachyos", "manjaro", "endeavouros"}),
        ("debian", {"debian", "ubuntu", "linuxmint", "pop"}),
        ("fedora", {"fedora", "rhel", "centos"}),
        ("suse", {"suse", "opensuse"}),
    ):
        if ids & names:
            return Host(system, family)
    return Host(system, "unknown")


VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parse_version(text: str | None) -> tuple[int, int, int] | None:
    """First dotted version number in ``text`` as a 3-tuple."""
    if not text:
        return None
    match = VERSION_RE.search(text)
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]
