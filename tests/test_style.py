import io

from claude_toolkit import doctor, lsp, runq, sessions
from claude_toolkit.style import Spinner, Style, color_wanted

COLOR = Style(enabled=True, truecolor=True)
PLAIN = Style()


class Tty(io.StringIO):
    def isatty(self):
        return True


def test_plain_style_returns_text_unchanged():
    assert PLAIN.err("x", bold=True) == "x"
    assert PLAIN.header("ctk doctor", "/p") == "ctk doctor · /p"
    assert PLAIN.bar(5, 10) == ""
    assert PLAIN.command("ls") == "ls"


def test_colour_rules(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert color_wanted(Tty()) is True
    assert color_wanted(io.StringIO()) is False, "pipes (and agents) get plain text"
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert color_wanted(io.StringIO()) is True
    monkeypatch.setenv("NO_COLOR", "")
    assert color_wanted(Tty()) is False, "NO_COLOR always wins"


def test_truecolor_and_basic_palettes():
    assert "38;2;" in COLOR.ok("x") and "\x1b[32m" in Style(enabled=True).ok("x")


def test_bar_scales_with_eighths():
    full = COLOR.bar(10, 10, width=4)
    half = COLOR.bar(5, 10, width=4)
    assert "████" in full and "██" in half and "███" not in half
    assert "▏" in COLOR.bar(0.01, 10, width=4), "tiny values still show a sliver"


def test_styled_renderers_colour_but_keep_the_facts():
    report = doctor.Report("/p", [doctor.Finding("error", "node", "node 26 does not satisfy .nvmrc (24)", "nvm use")])
    text = doctor.render(report, style=COLOR)
    assert "\x1b[" in text and "node 26 does not satisfy" in text and "nvm use" in text and "1 error" in text
    out = runq.summarise(["pytest"], "FAILED t.py::a - boom\n1 failed in 0.1s\n", 1, None, style=COLOR, elapsed=1.25)
    assert "FAILED" in out and "1.2s" in out and "exit 1" in out
    summary = sessions.summarise([])
    assert "Top tools" in sessions.render(summary, "all time", style=COLOR)
    assert "no languages" in lsp.render(lsp.Path("/p"), [], lsp.Host("linux", "arch"), style=COLOR)


def test_spinner_is_silent_without_a_terminal():
    stream = io.StringIO()
    with Spinner("work", style=COLOR, stream=stream):
        pass
    assert stream.getvalue() == ""
