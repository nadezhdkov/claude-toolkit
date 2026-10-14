# Changelog fragments

Every pull request that changes behaviour adds **one small file here** instead of editing
`docs/CHANGELOG.md`. A shared file is a conflict waiting to happen: with two pull requests open, both write at
the top of `[Unreleased]`, and whichever merges second has to be fixed by hand. Separate files never meet.

```bash
echo "- `ctk foo`: what it does, in a sentence or two." > docs/changelog.d/foo.added.md
```

- **Name**: `<slug>.<category>.md`, where the slug is anything unique to your change (the branch name works)
  and the category is `added`, `changed`, `deprecated`, `removed`, `fixed` or `security`
  ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)).
- **Content**: the entry, written as it should read in the changelog. A leading `- ` is optional; extra lines
  are indented for you.
- **At a release** (`make release`) the fragments are added to the matching `###` sections of the new version,
  in file name order, and the files are deleted. `make changelog` previews the result.
- Entries already written in `[Unreleased]` stay where they are and are released with the fragments.
- CI/docs-only changes can still take the `skip-changelog` label instead.

`python3 scripts/release.py check` (and CI) reports a file that would be ignored, such as a misspelled category.
