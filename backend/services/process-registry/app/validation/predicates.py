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


# --------------------------------------------------------------------------- #
# Schema-aware validation (batch-4) — validate a triage predicate against the pack's trigger schema so a
# non-existent field (reason_code vs reason_codes) or a type-incompatible op (eq on an array) is an
# AUTHORING-TIME error, not a silent runtime miss. Domain-neutral: the schema comes from the declared trigger
# artifact or the deployment's sample envelopes — never a hardcoded field name.
# --------------------------------------------------------------------------- #

# Ops allowed per JSON type. None ⇒ type unknown ⇒ skip the op check (be lenient).
_OPS_BY_TYPE: Mapping[str, Any] = {
    "array":   {"intersects", "in", "exists"},
    "string":  {"eq", "ne", "in", "starts_with", "exists"},
    "number":  {"eq", "ne", "in", "gt", "gte", "lt", "lte", "exists"},
    "integer": {"eq", "ne", "in", "gt", "gte", "lt", "lte", "exists"},
    "boolean": {"eq", "ne", "exists"},
    "object":  {"exists"},
    "null":    None,
}


def _json_type(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, (list, tuple, set)):
        return "array"
    if isinstance(v, Mapping):
        return "object"
    return "null"


def infer_field_types(envelopes: Any) -> dict:
    """Derive a ``{dotpath: json_type}`` map from one or more sample envelopes (deployment-provided trigger
    shape). Merges across samples; a later non-null type upgrades an earlier ``null``. Empty ⇒ no schema."""
    out: dict = {}

    def walk(obj: Any, prefix: str) -> None:
        if not isinstance(obj, Mapping):
            return
        for k, v in obj.items():
            path = f"{prefix}{k}"
            t = _json_type(v)
            if path not in out or out[path] == "null":
                out[path] = t
            if isinstance(v, Mapping):
                walk(v, path + ".")

    for env in (envelopes or []):
        walk(env, "")
    return out


def _schema_json_type(prop: Any) -> str:
    """A JSON-Schema property node → the json type in :func:`infer_field_types`' vocabulary, so a DECLARED
    trigger schema and a sample-derived one validate identically. ``integer`` folds to ``number`` (mirrors
    ``_json_type``, which has no integer); an ``enum`` with no ``type`` takes its first value's type."""
    if not isinstance(prop, Mapping):
        return "null"
    t = prop.get("type")
    if isinstance(t, list):                       # nullable union → first non-null
        t = next((x for x in t if x != "null"), None)
    if not t:
        enum = prop.get("enum")
        if isinstance(enum, list) and enum:
            return _json_type(enum[0])
        if isinstance(prop.get("properties"), Mapping):
            return "object"
        if "items" in prop:
            return "array"
        return "string"                           # indeterminate scalar
    return "number" if t == "integer" else str(t)


def flatten_schema_fields(json_schema: Any) -> dict:
    """Derive a ``{dotpath: json_type}`` map from a DECLARED trigger JSON-Schema (ADR-049) — the schema-first
    counterpart of :func:`infer_field_types`. Walks ``properties`` (recursing into nested objects); arrays and
    enums are leaves. Output shape/vocabulary is identical to ``infer_field_types`` so the Triage picker and
    predicate validation treat a declared trigger exactly like a sample-derived one. Empty ⇒ no schema."""
    out: dict = {}

    def walk(schema: Any, prefix: str) -> None:
        if not isinstance(schema, Mapping):
            return
        props = schema.get("properties")
        if not isinstance(props, Mapping):
            return
        for k, sub in props.items():
            path = f"{prefix}{k}"
            t = _schema_json_type(sub)
            out[path] = t
            if t == "object":
                walk(sub, path + ".")

    walk(json_schema, "")
    return out


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _nearest(field: str, candidates: Any) -> Any:
    """The closest schema property to ``field`` by edit distance (≤3 and shorter than the field), or None."""
    best, best_d = None, 99
    for c in candidates:
        d = _levenshtein(field, c)
        if d < best_d:
            best, best_d = c, d
    return best if best is not None and best_d <= 3 else None


def validate_predicate(predicate: Any, field_types: Any) -> list:
    """Schema-aware findings for a triage predicate. ``field_types`` is a ``{dotpath: json_type}`` map (from
    ``infer_field_types`` / a declared trigger schema); when empty the check degrades to a no-op (structural
    validation via ``check_predicate`` still applies). Returns a list of dict findings:
    ``triage_field_unknown`` (with a nearest-match ``suggestion``) and ``triage_op_type_mismatch``."""
    findings: list = []
    if not field_types:
        return findings

    def walk(node: Any) -> None:
        node = _to_dict(node)
        if not isinstance(node, Mapping):
            return
        if "all" in node or "any" in node:
            for c in node["all" if "all" in node else "any"]:
                walk(c)
            return
        if "not" in node:
            walk(node["not"])
            return
        if "field" in node and "op" in node:
            field, op = node.get("field"), node.get("op")
            if not isinstance(field, str) or not field:
                return  # structural check owns this
            if field not in field_types:
                suggestion = _nearest(field, field_types.keys())
                msg = f"triage field '{field}' is not on the trigger schema"
                if suggestion:
                    msg += f" — did you mean '{suggestion}'?"
                findings.append({"code": "triage_field_unknown", "field": field, "op": op,
                                 "suggestion": suggestion, "message": msg})
                return
            ftype = field_types[field]
            allowed = _OPS_BY_TYPE.get(ftype)
            if allowed is not None and op not in allowed:
                hint = " — use 'intersects'" if ftype == "array" else ""
                findings.append({"code": "triage_op_type_mismatch", "field": field, "op": op,
                                 "message": f"op '{op}' is not valid on {ftype} field '{field}'{hint}"})

    walk(predicate)
    return findings


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
