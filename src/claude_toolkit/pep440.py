"""Minimal PEP 440 specifier matching for ``requires-python`` style pins."""

from __future__ import annotations

import re

# Release, then the canonical pre (aN, bN, rcN), .postN and .devN segments in that order.
_CLAUSE = re.compile(
    r"^\s*(~=|==|!=|<=|>=|<|>|===)?\s*([0-9][0-9.]*)"
    r"(?:(?<=[0-9])(a|b|rc)([0-9]+))?"
    r"(?:(?<=[0-9])\.post([0-9]+))?"
    r"(?:(?<=[0-9])\.dev([0-9]+))?"
    r"(\.\*)?\s*$"
)
_PHASES = {"a": 0, "b": 1, "rc": 2}
_FINAL = (3, 0)


class UnsupportedSpecifier(ValueError):
    pass


def _tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(".") if part != "")


def _pad(version: tuple[int, ...], length: int) -> tuple[int, ...]:
    return version + (0,) * (length - len(version))


def _suffix_key(
    pre: str | None, pre_n: str | None, post: str | None, dev: str | None
) -> tuple[tuple[int, int], int, tuple[int, int]]:
    """PEP 440 order after the release: dev < a < b < rc < final < post."""
    if pre:
        pre_key = (_PHASES[pre], int(pre_n or 0))
    elif dev is not None and post is None:
        pre_key = (-1, 0)  # a bare .devN sorts before every pre-release
    else:
        pre_key = _FINAL
    post_key = int(post) if post is not None else -1
    dev_key = (0, int(dev)) if dev is not None else (1, 0)
    return pre_key, post_key, dev_key


_RELEASE = _suffix_key(None, None, None, None)


def satisfies(version: tuple[int, ...], spec: str) -> bool:
    """True if ``version`` satisfies every comma-separated clause of ``spec``.

    ``version`` is always a final release, so the PEP 440 rules that ``>V``
    skips post-releases of V and ``<V`` skips its pre-releases never apply.
    """
    for clause in filter(None, (part.strip() for part in spec.split(","))):
        match = _CLAUSE.match(clause)
        if not match:
            raise UnsupportedSpecifier(spec)
        op, raw, pre, pre_n, post, dev, wildcard = match.groups()
        op = op or "=="
        suffixed = pre is not None or post is not None or dev is not None
        if suffixed and (wildcard or op == "==="):
            raise UnsupportedSpecifier(spec)
        bound = _tuple(raw)
        length = max(len(bound), len(version))
        current = (_pad(version, length), *_RELEASE)
        target = (_pad(bound, length), *_suffix_key(pre, pre_n, post, dev))
        if wildcard:
            prefix_equal = version[: len(bound)] == bound
            ok = prefix_equal if op == "==" else not prefix_equal if op == "!=" else None
            if ok is None:
                raise UnsupportedSpecifier(spec)
        elif op == "~=":
            if len(bound) < 2:
                raise UnsupportedSpecifier(spec)
            ok = current >= target and version[: len(bound) - 1] == bound[:-1]
        else:
            ok = {
                "==": current == target,
                "===": current == target,
                "!=": current != target,
                ">=": current >= target,
                "<=": current <= target,
                ">": current > target,
                "<": current < target,
            }[op]
        if not ok:
            return False
    return True
