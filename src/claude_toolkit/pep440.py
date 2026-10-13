"""Minimal PEP 440 specifier matching for ``requires-python`` style pins."""

from __future__ import annotations

import re

_CLAUSE = re.compile(r"^\s*(~=|==|!=|<=|>=|<|>|===)?\s*([0-9][0-9.]*)(\.\*)?\s*$")


class UnsupportedSpecifier(ValueError):
    pass


def _tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(".") if part != "")


def _pad(version: tuple[int, ...], length: int) -> tuple[int, ...]:
    return version + (0,) * (length - len(version))


def satisfies(version: tuple[int, ...], spec: str) -> bool:
    """True if ``version`` satisfies every comma-separated clause of ``spec``."""
    for clause in filter(None, (part.strip() for part in spec.split(","))):
        match = _CLAUSE.match(clause)
        if not match:
            raise UnsupportedSpecifier(spec)
        op, raw, wildcard = match.group(1) or "==", match.group(2), match.group(3)
        bound = _tuple(raw)
        length = max(len(bound), len(version))
        current, target = _pad(version, length), _pad(bound, length)
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
