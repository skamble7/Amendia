# amendia_contracts/semver.py
"""A small semver range matcher for exactly the range forms the contracts use.

Supported specs:
- exact pin:            ``1.2.0``
- caret:                ``^1.2.0`` → ``>=1.2.0 <2.0.0`` (npm caret-zero rules)
- bounded comparators:  ``>=1.0.0 <2.0.0`` (space-separated, ops ``>=, >, <=, <, =``)

No third-party dependency; ~100 lines. ``satisfies(version, spec)`` is the entry point.
"""
from __future__ import annotations

from typing import List, Tuple

Version = Tuple[int, int, int]
_OPS = (">=", "<=", ">", "<", "=")


def parse_version(v: str) -> Version:
    """Parse an exact ``MAJOR.MINOR.PATCH`` string into a tuple of ints."""
    if not isinstance(v, str):
        raise TypeError(f"version must be a string, got {type(v).__name__}")
    parts = v.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"invalid semver '{v}': expected MAJOR.MINOR.PATCH")
    try:
        a, b, c = (int(p) for p in parts)
    except ValueError:
        raise ValueError(f"invalid semver '{v}': components must be integers")
    if a < 0 or b < 0 or c < 0:
        raise ValueError(f"invalid semver '{v}': components must be non-negative")
    return (a, b, c)


def is_exact(spec: str) -> bool:
    """True if the spec is a bare exact pin (no operators/ranges)."""
    s = spec.strip()
    return not s.startswith("^") and not any(op in s for op in ("<", ">", "=")) and " " not in s


def _caret_upper(base: Version) -> Version:
    a, b, c = base
    if a > 0:
        return (a + 1, 0, 0)
    if b > 0:
        return (a, b + 1, 0)
    # a == b == 0 → bump patch (covers ^0.0.3 → <0.0.4 and ^0.0.0 → <0.0.1)
    return (a, b, c + 1)


def _split_comparator(token: str) -> Tuple[str, str]:
    for op in _OPS:
        if token.startswith(op):
            return op, token[len(op):]
    return "=", token  # a bare version means an exact match


def _comparators(spec: str) -> List[Tuple[str, Version]]:
    s = spec.strip()
    if not s:
        raise ValueError("empty version spec")
    if s.startswith("^"):
        base = parse_version(s[1:])
        return [(">=", base), ("<", _caret_upper(base))]
    out: List[Tuple[str, Version]] = []
    for token in s.split():
        op, ver = _split_comparator(token)
        out.append((op, parse_version(ver)))
    if not out:
        raise ValueError(f"invalid version spec '{spec}'")
    return out


def _test(ver: Version, op: str, bound: Version) -> bool:
    if op == "=":
        return ver == bound
    if op == ">":
        return ver > bound
    if op == ">=":
        return ver >= bound
    if op == "<":
        return ver < bound
    if op == "<=":
        return ver <= bound
    raise ValueError(f"unknown comparator '{op}'")  # pragma: no cover


def satisfies(version: str, spec: str) -> bool:
    """Return True if the exact ``version`` satisfies ``spec``. Raises on malformed input."""
    ver = parse_version(version)
    return all(_test(ver, op, bound) for op, bound in _comparators(spec))
