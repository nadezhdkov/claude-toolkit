- The changelog is now written in fragments: a pull request adds `docs/changelog.d/<slug>.<category>.md`
  instead of editing `docs/CHANGELOG.md`, so two open pull requests no longer conflict at the top of
  `[Unreleased]`. `make release` folds the fragments into the new version's sections and deletes them;
  `make changelog` previews the result; the `Changelog` check accepts a fragment or the old edit; and
  `scripts/release.py check` reports a fragment that would be ignored. Entries already in `[Unreleased]`
  are kept.
