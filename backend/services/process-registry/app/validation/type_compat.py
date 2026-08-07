# app/validation/type_compat.py
"""Domain-neutral JSON-Schema type compatibility (ADR-052 follow-up).

Onboarding maps a SOURCE (a trigger dotpath, or an upstream artifact dotpath) into a capability/tool input
FIELD. If the source's JSON *type* can never satisfy the field's declared type — an ``object`` into a
``string``, an ``array``-of-``object`` into an ``array``-of-``string`` — the tool call is rejected at runtime
(the MCP server type-checks its closed ``inputSchema``: ``isError`` → ``MCP_TOOL_ERROR``, previously masked as a
compliance "hold"). This module decides that compatibility from the two SCHEMAS alone, at design time.

Verdicts: ``"compatible"`` | ``"incompatible"`` | ``"unknown"``. The guard flags/blocks ONLY ``"incompatible"``
(a definite, structural mismatch). Anything the schemas can't determine — an absent/opaque side, a permissive
target — is ``"unknown"`` and NEVER blocks (graceful degradation, mirroring ADR-057). Compares JSON *types*
only; it knows no business nouns.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

# Scalar JSON types (a "container" is object/array).
_SCALARS = {"string", "number", "integer", "boolean"}


def _effective(schema: Any) -> Optional[dict]:
    """Unwrap a nullable ``anyOf``/``oneOf`` union to its single non-null branch. Returns the schema dict, or
    ``None`` when it's absent or a genuinely ambiguous union (≥2 non-null branches → we can't decide → unknown)."""
    if not isinstance(schema, Mapping):
        return None
    for key in ("anyOf", "oneOf"):
        branches = schema.get(key)
        if isinstance(branches, list):
            non_null = [b for b in branches if isinstance(b, Mapping) and b.get("type") != "null"]
            return dict(non_null[0]) if len(non_null) == 1 else None
    return dict(schema)


def _type_of(schema: Mapping) -> Optional[str]:
    """The declared JSON type of a schema node (``integer`` kept distinct here; folded to number by callers).
    ``None`` when indeterminate (no ``type`` and no structural hint) — i.e. permissive/opaque."""
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), None)
    if isinstance(t, str):
        return t
    if isinstance(schema.get("properties"), Mapping):
        return "object"
    if "items" in schema:
        return "array"
    return None  # no type, no structure → permissive/opaque


def _is_permissive(schema: Mapping) -> bool:
    """A target that accepts anything of interest: no declared type/structure, or an open object with no
    declared properties (additionalProperties not false and no ``properties``)."""
    t = _type_of(schema)
    if t is None and not schema.get("enum"):
        return True
    if t == "object" and not schema.get("properties") and schema.get("additionalProperties") is not False:
        return True
    return False


def schema_type_compat(source: Any, target: Any) -> str:
    """Can a value shaped like ``source`` satisfy the declared ``target`` type? Returns
    ``compatible`` / ``incompatible`` / ``unknown``. Recurses object properties (declared target props only)
    and array ``items``. Conservative: only a STRUCTURAL container/scalar or array-item mismatch is
    ``incompatible``; scalar-vs-scalar is treated as compatible (coercible / not a definite break)."""
    tgt = _effective(target)
    if tgt is None:
        return "unknown"                       # no/ambiguous target constraint
    if _is_permissive(tgt):
        return "compatible"                    # target accepts anything relevant
    src = _effective(source)
    if src is None:
        return "unknown"                       # source absent/opaque → can't decide
    s_type = _type_of(src)
    t_type = _type_of(tgt)
    if s_type is None:
        return "unknown"                       # source opaque → don't block

    # Normalize integer → number for comparison.
    s_norm = "number" if s_type == "integer" else s_type
    t_norm = "number" if t_type == "integer" else t_type

    # Scalar target: a container source can never satisfy it.
    if t_norm in _SCALARS - {"integer"} or (t_norm is not None and t_norm not in ("object", "array")):
        if s_norm in ("object", "array"):
            return "incompatible"
        return "compatible"                    # scalar → scalar (incl. enum): not a definite break

    # Object target: source must be an object; each DECLARED target property that the source also declares
    # must itself be compatible (a declared-property type clash is incompatible — the `_typed_open` case).
    if t_norm == "object":
        if s_norm != "object":
            return "incompatible"
        s_props = src.get("properties") if isinstance(src.get("properties"), Mapping) else {}
        saw_unknown = False
        for name, t_sub in (tgt.get("properties") or {}).items():
            s_sub = s_props.get(name)
            if s_sub is None:
                continue                       # source doesn't carry this declared prop → tolerant, skip
            verdict = schema_type_compat(s_sub, t_sub)
            if verdict == "incompatible":
                return "incompatible"
            if verdict == "unknown":
                saw_unknown = True
        return "unknown" if saw_unknown and not s_props else "compatible"

    # Array target: source must be an array; the element types must be compatible.
    if t_norm == "array":
        if s_norm != "array":
            return "incompatible"
        return schema_type_compat(src.get("items"), tgt.get("items"))

    return "unknown"


def describe_mismatch(source: Any, target: Any, _path: str = "") -> str:
    """Best-effort human string for the deepest leaf where ``source`` can't satisfy ``target`` —
    e.g. ``"'account': object cannot satisfy string"`` or ``"'[]': object cannot satisfy string"``. Empty
    string when compatible/unknown. Mirrors :func:`schema_type_compat`'s incompatible rules; for MESSAGES
    only (the gate is :func:`schema_type_compat`)."""
    tgt = _effective(target)
    src = _effective(source)
    if tgt is None or _is_permissive(tgt) or src is None:
        return ""
    s = _type_of(src)
    t = _type_of(tgt)
    if s is None:
        return ""
    s_norm = "number" if s == "integer" else s
    t_norm = "number" if t == "integer" else t
    loc = _path or "<root>"
    if t_norm not in ("object", "array"):
        return f"'{loc}': {s_norm} cannot satisfy {t_norm}" if s_norm in ("object", "array") else ""
    if t_norm == "object":
        if s_norm != "object":
            return f"'{loc}': {s_norm} cannot satisfy object"
        s_props = src.get("properties") if isinstance(src.get("properties"), Mapping) else {}
        for name, t_sub in (tgt.get("properties") or {}).items():
            if name in s_props:
                d = describe_mismatch(s_props[name], t_sub, f"{_path}.{name}" if _path else name)
                if d:
                    return d
        return ""
    if s_norm != "array":
        return f"'{loc}': {s_norm} cannot satisfy array"
    return describe_mismatch(src.get("items"), tgt.get("items"), f"{_path}[]")


def schema_at_path(schema: Any, dotpath: Optional[str]) -> Optional[dict]:
    """Navigate a JSON-Schema to the sub-schema at ``dotpath`` (``a.b.c``), walking ``properties`` and
    unwrapping nullable unions at each hop. Empty/None path → the schema itself. Returns ``None`` when a hop
    isn't a declared object property (source shape unknown there → the caller treats it as ``unknown``)."""
    node = _effective(schema)
    if node is None:
        return None
    if not dotpath:
        return node
    for part in dotpath.split("."):
        props = node.get("properties") if isinstance(node.get("properties"), Mapping) else None
        nxt = props.get(part) if props else None
        node = _effective(nxt)
        if node is None:
            return None
    return node
