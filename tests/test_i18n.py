import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "docs" / "i18n"
LANGUAGES = {"pt-BR": "Português (Brasil)", "es": "Español", "de": "Deutsch", "zh-CN": "简体中文"}
PAGES = {"README.md": ROOT / "README.md", "installation.md": ROOT / "docs" / "installation.md"}
FENCE = re.compile(r"^```.*?^```$", re.MULTILINE | re.DOTALL)
LINK = re.compile(r"(?<!\\)(?:!\[[^\]]*\]|\[[^\]]*\])\(([^)\s]+)\)|<img [^>]*src=\"([^\"]+)\"")
CASES = [(code, page) for code in LANGUAGES for page in PAGES]


def prose(text: str) -> str:
    return FENCE.sub("", text)


def headings(text: str) -> list[int]:
    return [len(m.group(1)) for m in re.finditer(r"^(#{1,6}) ", prose(text), re.MULTILINE)]


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, no punctuation, spaces to hyphens."""
    heading = heading.replace("`", "").strip().lower()
    return re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")


def anchors(text: str) -> set[str]:
    return {slug(m.group(2)) for m in re.finditer(r"^(#{1,6}) (.+)$", prose(text), re.MULTILINE)}


def links(text: str) -> list[str]:
    return [a or b for a, b in LINK.findall(prose(text)) if not (a or b).startswith(("http://", "https://", "mailto:"))]


@pytest.mark.parametrize(("code", "page"), CASES)
def test_translation_has_the_structure_of_the_english_page(code, page):
    english = PAGES[page].read_text(encoding="utf-8")
    translated = (I18N / code / page).read_text(encoding="utf-8")
    assert headings(translated) == headings(english), "same headings, in the same order and level"
    assert FENCE.findall(translated) == FENCE.findall(english), "code blocks are not translated"
    rows = lambda text: [line.count("|") for line in prose(text).splitlines() if line.startswith("|")]  # noqa: E731
    assert rows(translated) == rows(english), "same tables, rows and columns"
    assert len(re.findall(r"<img ", translated)) == len(re.findall(r"<img ", english))


@pytest.mark.parametrize(("code", "page"), CASES)
def test_links_and_anchors_resolve(code, page):
    path = I18N / code / page
    text = path.read_text(encoding="utf-8")
    for link in links(text):
        target, _, fragment = link.partition("#")
        file = (path.parent / target).resolve() if target else path
        assert file.exists(), f"{code}/{page}: {link} does not exist"
        if fragment and file.suffix == ".md":
            assert fragment in anchors(file.read_text(encoding="utf-8")), f"{code}/{page}: no heading for {link}"


@pytest.mark.parametrize(("code", "page"), CASES)
def test_language_switcher_lists_every_language_and_the_english_page(code, page):
    text = (I18N / code / page).read_text(encoding="utf-8")
    switcher = next(line for line in text.splitlines() if "English" in line and "Deutsch" in line)
    for name in LANGUAGES.values():
        assert name in switcher
    english = "../../../README.md" if page == "README.md" else "../../installation.md"
    assert f"[English]({english})" in switcher
    for other in LANGUAGES:
        if other != code:
            assert f"../{other}/{page})" in switcher


@pytest.mark.parametrize("page", ["README.md", "installation.md"])
def test_english_pages_link_every_translation(page):
    english = PAGES[page].read_text(encoding="utf-8")
    for code in LANGUAGES:
        assert (I18N / code / page).exists()
        assert f"i18n/{code}/{page}" in english


def test_the_index_lists_every_language():
    index = (I18N / "README.md").read_text(encoding="utf-8")
    for code, name in LANGUAGES.items():
        assert name in index and f"{code}/README.md" in index and f"{code}/installation.md" in index
