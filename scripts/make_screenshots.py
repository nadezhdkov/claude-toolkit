"""Regenerate docs/assets/screenshots/*.svg from a synthetic demo environment.

Run: uv run python scripts/make_screenshots.py
Uses a throwaway HOME with a demo project and fake transcripts, so no real
paths, projects or session data end up in the images.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets" / "screenshots"
RENDER = ROOT / "scripts" / "render_terminal.py"

TEST_FILE = """import pytest


@pytest.mark.parametrize("case", range(118))
def test_api_contract(case):
    assert case >= 0


def test_login():
    status = 500
    assert status == 200, f"expected 200, got {status}"


def test_logout():
    session = {}
    assert session["token"]
"""


def demo_home(base: Path) -> Path:
    home = base / "home"
    app = home / "projects" / "shop-api"
    (app / "tests").mkdir(parents=True)
    (app / ".nvmrc").write_text("22.12.0\n", encoding="utf-8")
    (app / "package.json").write_text(
        json.dumps({"engines": {"node": "^22.12"}, "packageManager": "npm@10.9.0"}), encoding="utf-8"
    )
    (app / "package-lock.json").write_text("{}", encoding="utf-8")
    (app / "tests" / "test_api.py").write_text(TEST_FILE, encoding="utf-8")
    (app / "pytest.ini").write_text("[pytest]\naddopts = -p no:cacheprovider\n", encoding="utf-8")
    for name in ("server.ts", "routes.ts", "db.ts", "auth.ts"):
        (app / "src" / name).parent.mkdir(exist_ok=True)
        (app / "src" / name).write_text("", encoding="utf-8")
    for name in ("app.py", "jobs.py", "models.py"):
        (app / "workers" / name).parent.mkdir(exist_ok=True)
        (app / "workers" / name).write_text("", encoding="utf-8")
    for name in ("main.rs", "lib.rs", "codec.rs"):
        (app / "native" / name).parent.mkdir(exist_ok=True)
        (app / "native" / name).write_text("", encoding="utf-8")
    plugins = home / ".claude" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"rust-analyzer-lsp@claude-plugins-official": []}}), encoding="utf-8"
    )
    _fake_transcripts(home / ".claude" / "projects" / "-home-demo-projects-shop-api")
    return home


def _fake_transcripts(directory: Path) -> None:
    directory.mkdir(parents=True)
    mix = [("Bash", 60), ("Read", 18), ("Edit", 12), ("Write", 6), ("Grep", 5), ("Glob", 3), ("WebSearch", 2)]
    for n in range(12):
        records, i = [], 0
        for name, count in mix:
            for _ in range(count + n % 3):
                data = {"command": "ctk runq -- pytest" if name == "Bash" and i % 9 == 0 else "ls"}
                records.append(
                    {
                        "type": "assistant",
                        "timestamp": f"2026-10-{10 + n % 3:02d}T10:00:00Z",
                        "cwd": "/home/demo/projects/shop-api",
                        "message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": data}]},
                    }
                )
                records.append(
                    {
                        "type": "user",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": f"t{i}",
                                    "content": "x" * (300 + 40 * (i % 25)),
                                    "is_error": i % 47 == 0,
                                }
                            ]
                        },
                    }
                )
                i += 1
        records.insert(
            10,
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "id": "s", "name": "Skill", "input": {"skill": "debug"}}]},
            },
        )
        (directory / f"session-{n}.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def shoot(name: str, title: str, command: list[str], env: dict, cwd: Path) -> None:
    subprocess.run(
        [sys.executable, str(RENDER), str(OUT / f"{name}.svg"), "--title", title, "--", *command],
        env=env,
        cwd=cwd,
        check=True,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ctk-shots-") as tmp:
        home = demo_home(Path(tmp))
        app = home / "projects" / "shop-api"
        ctk = [sys.executable, "-m", "claude_toolkit.cli"]
        # The venv's bin dir on PATH lets screenshots show plain `pytest`, not an absolute path.
        path = os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])
        env = {**os.environ, "HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache"), "PATH": path}
        env.pop("VIRTUAL_ENV", None)
        shoot("overview", "ctk", ctk, env, app)
        shoot("doctor", "ctk doctor", [*ctk, "doctor"], env, app)
        shoot("runq", "ctk runq -- pytest -q", [*ctk, "runq", "--", "pytest", "-q"], env, app)
        shoot("lsp", "ctk lsp", [*ctk, "lsp"], env, app)
        shoot("sessions", "ctk sessions", [*ctk, "sessions"], env, app)
    leaked = [p.name for p in OUT.glob("*.svg") if str(Path.home()) in p.read_text(encoding="utf-8")]
    if leaked:
        raise SystemExit(f"real home directory leaked into {leaked}")
    print(f"wrote {sorted(p.name for p in OUT.glob('*.svg'))}")


if __name__ == "__main__":
    main()
