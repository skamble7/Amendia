# app/validation/predicates.py
"""Pure triage-predicate evaluator (no I/O).

Walks the ``all``/``any``/``not``/leaf tree from a manifest triage rule and evaluates
it against a normalized exception envelope (a plain dict). Reused verbatim by pack
validation (rule syntax check + dry-run) and by ``/resolve``.

The predicate may be supplied either as a raw dict (from Mongo/JSON) or as one of the
``amendia_contracts.process_pack`` predicate models — both are normalized to dicts here.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

_LEAF_OPS = {"eq", "ne", "in", "starts_with", "intersects", "exists", "gt", "gte", "lt", "lte"}

_MISSING = object()


class PredicateSyntaxError(ValueError):
    """Raised by check_predicate on a structurally invalid predicate."""


def _to_dict(node: Any) -> Any:
    """Normalize a pydantic predicate model (or nested) to plain dict/list."""
    if hasattr(node, "model_dump"):
        return node.model_dump(by_alias=True)
    return node


def _resolve_path(envelope: Mapping[str, Any], path: str) -> Any:
    cur: Any = envelope
    for seg in path.split("."):
        if isinstance(cur, Mapping) and seg in cur:
            cur = cur[seg]
        else:
            return _MISSING
    return cur


def _as_list(v: Any) -> list:
    if isinstance(v, (list, tuple, set)):
        return list(v)
    return [v]


def _coerce_number(v: Any) -> Any:
    """Best-effort numeric/ISO-date coercion for ordered comparisons."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, str):
        try:
            return float(v) if ("." in v or "e" in v.lower()) else int(v)
        except ValueError:
            return v  # fall back to string/ISO-date ordering (lexicographic on ISO works)
    return v


def _eval_leaf(envelope: Mapping[str, Any], node: Mapping[str, Any]) -> bool:
    field = node["field"]
    op = node["op"]
    value = node.get("value")
    actual = _resolve_path(envelope, field)

    if op == "exists":
        return actual is not _MISSING
    if actual is _MISSING:
        return False  # every op except `exists` is false on a missing path

    if op == "eq":
        return actual == value
    if op == "ne":
        return actual != value
    if op == "in":
        return actual in _as_list(value)
    if op == "starts_with":
        return isinstance(actual, str) and isinstance(value, str) and actual.startswith(value)
    if op == "intersects":
        return len(set(_as_list(actual)) & set(_as_list(value))) > 0
    if op in ("gt", "gte", "lt", "lte"):
        a, b = _coerce_number(actual), _coerce_number(value)
        try:
            if op == "gt":
                return a > b
            if op == "gte":
                return a >= b
            if op == "lt":
                return a < b
            return a <= b
        except TypeError:
            return False
    raise PredicateSyntaxError(f"unknown op '{op}'")


def evaluate(predicate: Any, envelope: Mapping[str, Any]) -> bool:
    """Evaluate a predicate (dict or model) against an envelope dict."""
    node = _to_dict(predicate)
    if not isinstance(node, Mapping):
        raise PredicateSyntaxError(f"predicate must be an object, got {type(node).__name__}")
    if "all" in node:
        return all(evaluate(c, envelope) for c in node["all"])
    if "any" in node:
        return any(evaluate(c, envelope) for c in node["any"])
    if "not" in node:
        return not evaluate(node["not"], envelope)
    if "field" in node and "op" in node:
        return _eval_leaf(envelope, node)
    raise PredicateSyntaxError(f"unrecognized predicate node: {sorted(node.keys())}")


def check_predicate(predicate: Any, *, _depth: int = 0) -> None:
    """Structural syntax check (raises PredicateSyntaxError). No envelope needed."""
    if _depth > 50:
        raise PredicateSyntaxError("predicate nested too deeply")
    node = _to_dict(predicate)
    if not isinstance(node, Mapping):
        raise PredicateSyntaxError("predicate must be an object")
    keys = set(node.keys())
    if "all" in keys or "any" in keys:
        key = "all" if "all" in keys else "any"
        children = node[key]
        if not isinstance(children, list) or not children:
            raise PredicateSyntaxError(f"'{key}' must be a non-empty array")
        for c in children:
            check_predicate(c, _depth=_depth + 1)
        return
    if "not" in keys:
        check_predicate(node["not"], _depth=_depth + 1)
        return
    if "field" in keys and "op" in keys:
        if not isinstance(node["field"], str) or not node["field"]:
            raise PredicateSyntaxError("leaf 'field' must be a non-empty string")
        if node["op"] not in _LEAF_OPS:
            raise PredicateSyntaxError(f"leaf 'op' must be one of {sorted(_LEAF_OPS)}")
        return
    raise PredicateSyntaxError(f"unrecognized predicate node: {sorted(keys)}")
