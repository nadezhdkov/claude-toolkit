"""Just enough npm-style range matching to check toolchain pins.

Supports exact versions, partial versions (``24``, ``24.11``), ``x``/``*``
wildcards, ``^``, ``~``, comparison operators, hyphen ranges (``1.2.3 - 2.3.4``),
space-separated AND and ``||``. Anything else is reported as unsupported instead
of guessed.
"""

from __future__ import annotations

import re

Version = tuple[int, int, int]

_COMPARATOR = re.compile(r"^(\^|~|>=|<=|>|<|=)?v?(\d+|[xX*])(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?(?:[-+].*)?$")


class UnsupportedRange(ValueError):
    pass


def _parts(match: re.Match) -> list[int | None]:
    out: list[int | None] = []
    for part in match.groups()[1:]:
        out.append(None if part is None or part in ("x", "X", "*") else int(part))
    return out


def _bounds(op: str, parts: list[int | None]) -> list[tuple[str, Version]]:
    major, minor, patch = parts
    if major is None:
        return []
    low: Version = (major, minor or 0, patch or 0)
    if op in ("", "="):
        if minor is None:
            return [(">=", low), ("<", (major + 1, 0, 0))]
        if patch is None:
            return [(">=", low), ("<", (major, minor + 1, 0))]
        return [("=", low)]
    if op == "^":
        if major > 0 or minor is None:
            return [(">=", low), ("<", (major + 1, 0, 0))]
        if minor > 0 or patch is None:
            return [(">=", low), ("<", (0, minor + 1, 0))]
        return [(">=", low), ("<", (0, 0, patch + 1))]
    if op == "~":
        if minor is None:
            return [(">=", low), ("<", (major + 1, 0, 0))]
        return [(">=", low), ("<", (major, minor + 1, 0))]
    if op in (">", "<=") and patch is None:
        # A partial version is a whole range: ">1.2" is above all of 1.2.x,
        # "<=1.2" includes all of it.
        after: Version = (major + 1, 0, 0) if minor is None else (major, minor + 1, 0)
        return [(">=" if op == ">" else "<", after)]
    return [(op, low)]


def _is_plain_version(token: str) -> bool:
    """A hyphen-range bound: a version without operator whose major is a number."""
    match = _COMPARATOR.match(token)
    return bool(match) and match.group(1) is None and match.group(2) not in ("x", "X", "*")


def _check(version: Version, op: str, bound: Version) -> bool:
    return {
        "=": version == bound,
        ">=": version >= bound,
        "<=": version <= bound,
        ">": version > bound,
        "<": version < bound,
    }[op]


def satisfies(version: Version, spec: str) -> bool:
    """True if ``version`` matches an npm-style range ``spec``."""
    spec = spec.strip()
    if spec in ("", "*", "x", "latest", "lts", "lts/*", "node", "stable"):
        return True
    for alternative in spec.split("||"):
        tokens = alternative.split()
        # Allow ">= 18" with a space between operator and version.
        merged: list[str] = []
        for token in tokens:
            if merged and merged[-1] in ("^", "~", ">=", "<=", ">", "<", "="):
                merged[-1] += token
            else:
                merged.append(token)
        if not merged:
            return True
        # A hyphen range "A - B" is ">=A <=B"; _bounds gives a partial B its npm meaning.
        expanded: list[str] = []
        i = 0
        while i < len(merged):
            if merged[i] == "-":
                raise UnsupportedRange(spec)
            if i + 1 < len(merged) and merged[i + 1] == "-":
                if i + 2 >= len(merged) or not all(_is_plain_version(t) for t in (merged[i], merged[i + 2])):
                    raise UnsupportedRange(spec)
                expanded += [">=" + merged[i], "<=" + merged[i + 2]]
                i += 3
            else:
                expanded.append(merged[i])
                i += 1
        ok = True
        for token in expanded:
            match = _COMPARATOR.match(token)
            if not match:
                raise UnsupportedRange(spec)
            for op, bound in _bounds(match.group(1) or "", _parts(match)):
                if not _check(version, op, bound):
                    ok = False
        if ok:
            return True
    return False
