"""Shared pieces for hooks: the event, the outcome, configuration and state."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_NAME = ".claude-toolkit.toml"
STATE_MAX_AGE = 7 * 24 * 3600


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    path = Path(base) / "claude-toolkit" / "hooks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "claude-toolkit"


# --- Configuration ------------------------------------------------------------


@dataclass
class Config:
    """``[hooks]`` tables merged from the user config and the project's file."""

    disabled: set[str] = field(default_factory=set)
    all_disabled: bool = False
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)

    def enabled(self, hook: str) -> bool:
        return not self.all_disabled and hook not in self.disabled

    def get(self, hook: str, key: str, default: Any) -> Any:
        value = self.settings.get(hook, {}).get(key, default)
        return value if isinstance(value, type(default)) else default

    def merge(self, data: dict[str, Any]) -> None:
        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            return
        disable = hooks.get("disable")
        if disable is True:
            self.all_disabled = True
        elif isinstance(disable, list):
            self.disabled.update(str(name) for name in disable)
        for name, table in hooks.items():
            if isinstance(table, dict):
                self.settings.setdefault(name, {}).update(table)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def find_project_config(start: Path) -> Path | None:
    """Nearest ``.claude-toolkit.toml`` from ``start`` upwards, stopping at the home directory."""
    home = Path.home()
    for directory in (start, *start.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
        if directory == home:
            break
    return None


def load_config(cwd: Path) -> Config:
    config = Config()
    config.merge(_read_toml(config_home() / "config.toml"))
    project = find_project_config(cwd)
    if project:
        config.merge(_read_toml(project))
    return config


# --- Event and outcome -------------------------------------------------------


@dataclass
class Event:
    name: str
    session_id: str
    cwd: Path
    data: dict[str, Any]
    config: Config = field(default_factory=Config)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Event:
        cwd = Path(str(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()))
        return cls(str(data.get("hook_event_name", "")), str(data.get("session_id") or "nosession"), cwd, data)

    @property
    def tool_input(self) -> dict[str, Any]:
        value = self.data.get("tool_input")
        return value if isinstance(value, dict) else {}


@dataclass
class Outcome:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""

    @classmethod
    def json(cls, payload: dict[str, Any]) -> Outcome:
        return cls(stdout=json.dumps(payload, ensure_ascii=False))

    @classmethod
    def context(cls, event_name: str, text: str) -> Outcome:
        """Tell Claude something without blocking (shown as a system reminder)."""
        return cls.json({"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": text}})

    @classmethod
    def message(cls, text: str) -> Outcome:
        """Show the user a warning; Claude does not see it."""
        return cls.json({"systemMessage": text})


# --- Projects and paths --------------------------------------------------------


def git_root(path: Path) -> Path | None:
    try:
        done = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else None


def project_root(cwd: Path) -> Path:
    return git_root(cwd) or cwd


def is_within(path: Path, root: Path) -> bool:
    """True when ``path`` is ``root`` or below it."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


# --- Per-session state ----------------------------------------------------------


class State:
    """A small JSON document per session and hook, kept in the cache for a week."""

    def __init__(self, session_id: str, hook: str):
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:80] or "nosession"
        self.directory = cache_dir() / "state"
        self.path = self.directory / f"{safe}.{hook}.json"

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.path)
        self._prune()

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def _prune(self) -> None:
        cutoff = time.time() - STATE_MAX_AGE
        for old in self.directory.glob("*.json"):
            try:
                if old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                pass
