# Translations

The documentation is written in English, which is the source of truth. These
translations of the two pages a new user needs first are kept in step with it:

| Language | README | Installation |
|---|---|---|
| Português (Brasil) | [README](pt-BR/README.md) | [installation](pt-BR/installation.md) |
| Español | [README](es/README.md) | [installation](es/installation.md) |
| Deutsch | [README](de/README.md) | [installation](de/installation.md) |
| 简体中文 | [README](zh-CN/README.md) | [installation](zh-CN/installation.md) |

The pages for each command, the design, the roadmap and the changelog are
English only; every translation links to them.

## Keeping them in step

`tests/test_i18n.py` compares each translation with its English page, so a
pull request that changes the English text fails until the translations follow:

- the same headings (count and level), tables (rows), images and code blocks;
- code blocks are **not translated**: commands, flags, output and the comments
  inside them stay exactly as in English;
- every relative link and image resolves to an existing file, and every `#anchor`
  link points to a heading of the same page;
- the language switcher lists every language, and each page links back to the
  English page.

Names stay in English in every language: commands (`ctk runq`), hooks, skills,
subagents, flags, file names and the product names.

## Adding a language

1. Copy `pt-BR/` to `docs/i18n/<code>/` (a BCP 47 tag such as `fr` or `ja`) and translate the two pages.
2. Add the language to `LANGUAGES` in `tests/test_i18n.py`, to the switcher line of every translated page,
   to the line under the badges in `README.md` and to the table above.
3. Run `uv run pytest tests/test_i18n.py`.

Corrections to the wording are welcome as pull requests, in the translation
file only.
