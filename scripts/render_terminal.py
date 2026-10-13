"""Render a command's coloured terminal output as an SVG "screenshot".

Usage: python scripts/render_terminal.py OUT.svg --title "ctk doctor" -- <command...>
The command runs with FORCE_COLOR=1 and COLORTERM=truecolor. Used to produce
the screenshots in docs/assets/screenshots.
"""

from __future__ import annotations

import html
import os
import re
import subprocess
import sys

SGR = re.compile(r"\x1b\[([0-9;]*)m")
OTHER_ESCAPES = re.compile(r"\x1b\[[0-9;?]*[A-Za-ln-z]|\r")
BASIC = {
    30: "#1e293b",
    31: "#f87171",
    32: "#4ade80",
    33: "#fbbf24",
    34: "#60a5fa",
    35: "#c084fc",
    36: "#38bdf8",
    37: "#e2e8f0",
    90: "#94a3b8",
    91: "#fca5a5",
    92: "#86efac",
    93: "#fde68a",
    94: "#93c5fd",
    95: "#d8b4fe",
    96: "#22d3ee",
    97: "#ffffff",
}
FG, BG = "#e2e8f0", "#0f172a"
CHAR_W, LINE_H, PAD, TOP = 8.4, 19, 18, 44


def spans(line: str, state: dict) -> list[tuple[str, dict]]:
    out, pos = [], 0
    for match in SGR.finditer(line):
        if match.start() > pos:
            out.append((line[pos : match.start()], dict(state)))
        codes = [int(c) for c in match.group(1).split(";") if c] or [0]
        i = 0
        while i < len(codes):
            code = codes[i]
            if code == 0:
                state.clear()
            elif code == 1:
                state["bold"] = True
            elif code == 2:
                state["dim"] = True
            elif code == 38 and codes[i + 1 : i + 2] == [2]:
                r, g, b = codes[i + 2 : i + 5]
                state["fg"] = f"#{r:02x}{g:02x}{b:02x}"
                i += 4
            elif code in BASIC:
                state["fg"] = BASIC[code]
            i += 1
        pos = match.end()
    if pos < len(line):
        out.append((line[pos:], dict(state)))
    return out


def render(text: str, title: str) -> str:
    text = OTHER_ESCAPES.sub("", text)
    lines = text.rstrip("\n").split("\n")
    width_chars = max([len(SGR.sub("", line)) for line in lines] + [60])
    width = int(width_chars * CHAR_W + 2 * PAD)
    height = int(TOP + len(lines) * LINE_H + PAD)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" rx="10" fill="{BG}"/>',
        '<circle cx="20" cy="18" r="6" fill="#f87171"/><circle cx="40" cy="18" r="6" fill="#fbbf24"/>'
        '<circle cx="60" cy="18" r="6" fill="#4ade80"/>',
        f'<text x="{width / 2}" y="22" text-anchor="middle" fill="#64748b" font-family="ui-sans-serif, sans-serif" '
        f'font-size="12">{html.escape(title)}</text>',
        "<g font-family=\"ui-monospace, SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', monospace\" "
        'font-size="14" xml:space="preserve">',
    ]
    state: dict = {}
    for row, line in enumerate(lines):
        y = TOP + row * LINE_H + 12
        tspans = []
        for chunk, st in spans(line, state):
            attrs = [f'fill="{st.get("fg", FG)}"']
            if st.get("bold"):
                attrs.append('font-weight="bold"')
            if st.get("dim"):
                attrs.append('opacity="0.6"')
            tspans.append(f"<tspan {' '.join(attrs)}>{html.escape(chunk)}</tspan>")
        parts.append(
            f'<text x="{PAD}" y="{y}" textLength="{len(SGR.sub("", line)) * CHAR_W}">{"".join(tspans)}</text>'
            if line.strip()
            else ""
        )
    parts.append("</g></svg>")
    return "\n".join(p for p in parts if p)


def main() -> None:
    args = sys.argv[1:]
    out = args.pop(0)
    title = "terminal"
    if args[:1] == ["--title"]:
        title = args[1]
        args = args[2:]
    if args[:1] == ["--"]:
        args = args[1:]
    env = {**os.environ, "FORCE_COLOR": "1", "COLORTERM": "truecolor", "COLUMNS": "100"}
    done = subprocess.run(args, capture_output=True, text=True, env=env, check=False)
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(render(done.stdout + done.stderr, title))


if __name__ == "__main__":
    main()
