# app/services/copilot/trigger.py
"""Resolve the user-provided trigger (the external event CONTRACT) into a JSON Schema.

Per ADR-052 refinement: the copilot infers the INTERNAL design, but the trigger is USER-PROVIDED — the operator
pastes either a JSON Schema or a sample event. When a sample is pasted, this derives a draft-2020-12 object schema
deterministically (E2 `$id` normalization happens later at declare_trigger). Domain-neutral.

The derived schema is deliberately OPEN and minimally-required. A trigger VALIDATES the fields the pack consumes;
it does not forbid extras. Real events routinely carry more (and sometimes fewer) fields than any one sample — a
nested pacs.008 wire exception has far more than a hand-picked sample — so closing the schema
(`additionalProperties:false`) or requiring every sampled field makes the ADR-047 fetch-back validation reject the
very event that dispatched here (``envelope_invalid``). Prefer optional; forbid nothing.
"""
from __future__ import annotations

from typing import Any, Dict

_DRAFT = "https://json-schema.org/draft/2020-12/schema"


def looks_like_json_schema(raw: Dict[str, Any]) -> bool:
    """Heuristic: a pasted object is already a JSON Schema (not a sample event) if it declares schema structure."""
    if not isinstance(raw, dict):
        return False
    if "$schema" in raw or "properties" in raw:
        return True
    # a bare `{"type": "object"|...}` with no domain fields reads as a schema, not a sample event
    return raw.get("type") in ("object", "array", "string", "number", "integer", "boolean") and len(raw) <= 2


def _type_of(value: Any) -> Dict[str, Any]:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        item = _type_of(value[0]) if value else {"type": "string"}
        return {"type": "array", "items": item}
    if isinstance(value, dict):
        return _object_schema(value)
    return {"type": "string"}   # null / unknown → permissive string


def _object_schema(obj: Dict[str, Any]) -> Dict[str, Any]:
    # OPEN + no `required`: a single sample can't tell us which fields are optional, and real events carry extras,
    # so we validate the SHAPE of the fields that ARE present without forbidding others or demanding any.
    return {"type": "object", "properties": {k: _type_of(v) for k, v in obj.items()}}


def schema_from_sample(sample: Dict[str, Any]) -> Dict[str, Any]:
    """Derive an OPEN draft-2020-12 object schema from a sample event (types inferred from the values; extras
    allowed; nothing required)."""
    schema = _object_schema(sample)
    schema["$schema"] = _DRAFT
    return schema


def resolve_trigger_schema(raw: Dict[str, Any]) -> Dict[str, Any]:
    """The user pasted a JSON Schema OR a sample event → return a normalized JSON Schema. Raises ValueError if the
    input isn't a JSON object at all (surfaced as a clean 4xx, not a crash)."""
    if not isinstance(raw, dict) or not raw:
        raise ValueError("the trigger must be a JSON object — a JSON Schema or a sample event")
    if looks_like_json_schema(raw):
        # Respect the schema the operator authored — including its `additionalProperties`. NEVER force-close it:
        # an authored open schema (the default) must stay open so real events with extra fields still validate.
        schema = dict(raw)
        schema.setdefault("type", "object")
        schema.setdefault("$schema", _DRAFT)
        return schema
    return schema_from_sample(raw)
