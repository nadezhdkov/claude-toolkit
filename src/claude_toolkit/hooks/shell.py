"""Approximate parsing of a Bash tool command into simple commands.

Good enough to find ``rm``, ``git push`` and friends behind ``&&``, pipes,
``sudo``, ``env VAR=1``, ``bash -c '…'`` and ``cd dir &&``. It does not
execute anything and never needs to be exact: guards built on it only warn or
block known patterns.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OPERATOR = re.compile(r"^[();<>|&]+$")
WRAPPERS = {"sudo", "doas", "env", "command", "builtin", "nohup", "time", "nice", "exec", "timeout", "stdbuf"}
WRAPPER_VALUE_OPTIONS = {"-u", "-g", "-n", "-C", "-o", "-e", "-i", "-s", "-k", "--user", "--group", "--signal"}
SHELLS = {"sh", "bash", "zsh", "dash", "fish"}


@dataclass(frozen=True)
class SimpleCommand:
    argv: list[str]
    cwd: Path

    @property
    def name(self) -> str:
        return os.path.basename(self.argv[0]) if self.argv else ""


def _tokens(text: str) -> list[str]:
    text = text.replace("\\\n", " ").replace("\n", " ; ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:  # unbalanced quotes: fall back to whitespace
        return text.split()


def _strip_wrappers(argv: list[str]) -> list[str]:
    while argv:
        if ASSIGNMENT.match(argv[0]):
            argv = argv[1:]
        elif os.path.basename(argv[0]) in WRAPPERS:
            wrapper, argv = os.path.basename(argv[0]), argv[1:]
            while argv and (argv[0].startswith("-") or ASSIGNMENT.match(argv[0])):
                takes_value = argv[0] in WRAPPER_VALUE_OPTIONS and len(argv) > 1
                argv = argv[2:] if takes_value else argv[1:]
            if wrapper == "timeout" and argv:
                argv = argv[1:]  # the duration
        else:
            break
    return argv


def expand(word: str, cwd: Path) -> Path | None:
    """The path a shell word names, or None when it depends on unknown variables."""
    home = str(Path.home())
    if word == "~" or word.startswith("~/"):
        word = home + word[1:]
    word = re.sub(r"\$\{HOME\}|\$HOME\b", lambda _: home, word)  # a function: Windows paths hold backslashes
    word = re.sub(r"\$\{PWD\}|\$PWD\b", lambda _: str(cwd), word)
    if "$" in word or "`" in word:
        return None
    path = Path(word) if os.path.isabs(word) else cwd / word
    return Path(os.path.normpath(path))


def split(command: str, cwd: Path, _depth: int = 0) -> list[SimpleCommand]:
    """Simple commands in order, each with the directory it would run in."""
    commands: list[SimpleCommand] = []
    current: list[str] = []
    skip_next = False

    def flush() -> None:
        nonlocal cwd
        argv = _strip_wrappers(current)
        if not argv:
            return
        name = os.path.basename(argv[0])
        if name == "cd":
            target = expand(argv[1], cwd) if len(argv) > 1 and argv[1] != "-" else Path.home()
            if target is not None:
                cwd = target
            return
        if name in SHELLS and "-c" in argv[1:-1] and _depth < 2:
            inner = argv[argv.index("-c", 1) + 1]
            commands.extend(split(inner, cwd, _depth + 1))
            return
        commands.append(SimpleCommand(argv, cwd))

    for token in _tokens(command):
        if skip_next:
            skip_next = False
            continue
        if OPERATOR.match(token):
            if "<" in token or ">" in token:
                if current and current[-1].isdigit():
                    current.pop()  # the descriptor in `2>`
                skip_next = True  # the file, descriptor or here-doc delimiter
                continue
            flush()
            current = []
            continue
        current.append(token)
    flush()
    return commands


@dataclass(frozen=True)
class GitCommand:
    subcommand: str
    args: list[str]
    cwd: Path


GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}


def as_git(command: SimpleCommand) -> GitCommand | None:
    """Split ``git [global options] <subcommand> args`` and apply ``-C``."""
    if command.name != "git":
        return None
    argv, cwd = command.argv[1:], command.cwd
    while argv and argv[0].startswith("-"):
        option = argv[0]
        if option in GIT_VALUE_OPTIONS and len(argv) > 1:
            if option == "-C":
                cwd = expand(argv[1], cwd) or cwd
            argv = argv[2:]
        else:
            argv = argv[1:]
    if not argv:
        return None
    return GitCommand(argv[0], argv[1:], cwd)
