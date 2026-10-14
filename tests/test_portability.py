import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "claude_toolkit"


def calls_without_encoding(path: Path) -> list[str]:
    """Text I/O that would use the locale encoding (cp1252 on Windows) instead of UTF-8."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call) or any(k.arg == "encoding" for k in node.keywords):
            continue
        func = node.func
        text_io = isinstance(func, ast.Attribute) and func.attr in ("read_text", "write_text")
        text_mode = any(k.arg == "text" and isinstance(k.value, ast.Constant) and k.value.value for k in node.keywords)
        builtin_open = isinstance(func, ast.Name) and func.id == "open"
        mode = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), None)
        binary = isinstance(mode, ast.Constant) and "b" in str(mode.value)
        if text_io or text_mode or (builtin_open and not binary):
            found.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
    return found


def test_all_text_io_is_utf8():
    missing = [where for path in sorted(SRC.rglob("*.py")) for where in calls_without_encoding(path)]
    assert missing == [], "add encoding='utf-8' (Windows defaults to its legacy code page)"
