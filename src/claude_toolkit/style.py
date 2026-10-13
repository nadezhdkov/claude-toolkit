"""Terminal styling: colour only for people, plain text for agents and pipes.

Colour is used when stdout is a terminal (or ``FORCE_COLOR``/``CLICOLOR_FORCE``
is set) and disabled by ``NO_COLOR`` or ``TERM=dumb``. When disabled, every
helper returns its input unchanged and decorative extras are skipped, so the
plain output stays compact for Claude Code and for logs.
"""

from __future__ import annotations

import itertools
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from typing import TextIO

# Palette taken from the logo: sky/cyan accents on slate.
_TRUE = {
    "accent": "38;2;56;189;248",
    "accent2": "38;2;34;211;238",
    "ok": "38;2;74;222;128",
    "warn": "38;2;251;191;36",
    "err": "38;2;248;113;113",
    "muted": "38;2;148;163;184",
    "bar": "38;2;56;189;248",
}
_BASIC = {"accent": "36", "accent2": "96", "ok": "32", "warn": "33", "err": "31", "muted": "90", "bar": "36"}
_BLOCKS = " ▏▎▍▌▋▊▉█"
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _flag(name: str) -> bool:
    value = os.environ.get(name)
    return value is not None and value not in ("", "0", "false")


def color_wanted(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stdout
    if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return False
    if _flag("FORCE_COLOR") or _flag("CLICOLOR_FORCE"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


@dataclass(frozen=True)
class Style:
    enabled: bool = False
    truecolor: bool = False

    @classmethod
    def detect(cls, stream: TextIO | None = None) -> Style:
        enabled = color_wanted(stream)
        truecolor = enabled and os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")
        return cls(enabled, truecolor)

    # --- primitives -------------------------------------------------------

    def _wrap(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled and text else text

    def _color(self, name: str) -> str:
        return (_TRUE if self.truecolor else _BASIC)[name]

    def bold(self, text: str) -> str:
        return self._wrap(text, "1")

    def accent(self, text: str, bold: bool = False) -> str:
        return self._wrap(text, ("1;" if bold else "") + self._color("accent"))

    def accent2(self, text: str) -> str:
        return self._wrap(text, self._color("accent2"))

    def ok(self, text: str, bold: bool = False) -> str:
        return self._wrap(text, ("1;" if bold else "") + self._color("ok"))

    def warn(self, text: str, bold: bool = False) -> str:
        return self._wrap(text, ("1;" if bold else "") + self._color("warn"))

    def err(self, text: str, bold: bool = False) -> str:
        return self._wrap(text, ("1;" if bold else "") + self._color("err"))

    def muted(self, text: str) -> str:
        return self._wrap(text, self._color("muted"))

    def level(self, level: str, text: str, bold: bool = False) -> str:
        return {"error": self.err, "warn": self.warn, "ok": self.ok}.get(level, self.muted)(text, bold)  # type: ignore[operator]

    # --- composites -------------------------------------------------------

    def header(self, command: str, subject: str = "") -> str:
        """``ctk doctor · subject`` in plain mode; a branded title when coloured."""
        if not self.enabled:
            return f"{command} · {subject}" if subject else command
        title = f"{self.accent('◆', bold=True)} {self.bold(command)}"
        return f"{title}  {self.muted(subject)}" if subject else title

    def bar(self, value: float, maximum: float, width: int = 24) -> str:
        """Unicode bar with eighth-block precision; empty in plain mode."""
        if not self.enabled or maximum <= 0:
            return ""
        eighths = round(width * 8 * min(value / maximum, 1.0))
        full, rest = divmod(eighths, 8)
        text = "█" * full + (_BLOCKS[rest] if rest else "")
        return self._wrap(text or "▏", self._color("bar"))

    def command(self, text: str) -> str:
        """A shell command the user can copy."""
        return f"{self.accent('$')} {self.bold(text)}" if self.enabled else text


def shorten_home(path: object) -> str:
    """Show paths under the home directory as ``~/...``."""
    text = str(path)
    home = os.path.expanduser("~")
    return (
        "~" + text[len(home) :] if home not in ("", "/") and (text == home or text.startswith(home + os.sep)) else text
    )


def terminal_width(default: int = 100) -> int:
    return shutil.get_terminal_size((default, 24)).columns


class Spinner:
    """Elapsed-time spinner on stderr, shown only on an interactive terminal."""

    def __init__(self, label: str, style: Style | None = None, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stderr
        self.style = style or Style.detect(self.stream)
        self.label = label
        self.active = self.style.enabled and hasattr(self.stream, "isatty") and self.stream.isatty()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> Spinner:
        if self.active:
            self._started = time.monotonic()
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def _spin(self) -> None:
        for frame in itertools.cycle(_SPINNER):
            if self._stop.wait(0.1):
                break
            elapsed = time.monotonic() - self._started
            line = f"{self.style.accent(frame)} {self.label} {self.style.muted(f'{elapsed:.0f}s')}"
            self.stream.write(f"\r\033[2K{line}")
            self.stream.flush()

    def __exit__(self, *exc: object) -> None:
        if self._thread:
            self._stop.set()
            self._thread.join()
            self.stream.write("\r\033[2K")
            self.stream.flush()
