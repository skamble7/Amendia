# schemas.py
"""Per-tool JSON Schemas (draft 2020-12) for the ACH-exposure **Closeout** segment MCP server.

Carried over verbatim from the combined ach_exposure server (ADR-063 split) — only this segment's tools plus the
shared ``notify_pega`` handback. Action tools (mark_completed / purge_working_data / notify_pega) carry the ack
floor; verify_disposition is a read-only check.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

DRAFT = "https://json-schema.org/draft/2020-12/schema"

_STR = {"type": "string"}
_NUM = {"type": "number"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}
_STR_ARR = {"type": "array", "items": {"type": "string"}}
_CONF = {"type": "number", "minimum": 0, "maximum": 1}


def _enum(*vals: str) -> Dict[str, Any]:
    return {"type": "string", "enum": list(vals)}


def _closed(properties: Dict[str, Any], *, required: Iterable[str] = ()) -> Dict[str, Any]:
    s: Dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": properties}
    if required:
        s["required"] = list(required)
    return s


def _typed_open(properties: Dict[str, Any]) -> Dict[str, Any]:
    """Nested input object that DECLARES its props (so Amendia derives a real HITL form) but stays tolerant
    (no ``additionalProperties: false``) so a caller may pass a whole upstream artifact with extra keys."""
    return {"type": "object", "properties": properties}


def _input(properties: Dict[str, Any]) -> Dict[str, Any]:
    """CLOSED input root: no required fields (dumb handlers read only what they need), but every declared field
    is the surface a binding's ``input_map`` may target. ``check_compliance`` enforces the closed root."""
    return {"$schema": DRAFT, "type": "object", "additionalProperties": False, "properties": properties}


def _output(properties: Dict[str, Any], *, required: Iterable[str] = ()) -> Dict[str, Any]:
    s = _closed(properties, required=required)
    s["$schema"] = DRAFT
    return s


# The §4 acknowledgement floor for side-effectful tools.
_ACK_PROPS: Dict[str, Any] = {
    "acknowledged": _BOOL,
    "action_id": _STR,
    "status": _enum("performed", "queued", "rejected"),
    "performed_at": {"type": "string", "format": "date-time"},
}
_ACK_REQUIRED = ["acknowledged", "action_id", "status"]


def _action_output(extra: Dict[str, Any], *, required: Iterable[str] = ()) -> Dict[str, Any]:
    props = {**_ACK_PROPS, **extra}
    return _output(props, required=[*_ACK_REQUIRED, *required])


# ============================ Segment C ============================ #

VERIFY_DISPOSITION_INPUT = _input({
    "case_id": _STR, "instruction": _STR,
    "execution": _typed_open({"instruction": _STR}),
})
VERIFY_DISPOSITION_OUTPUT = _output({   # read-only check — no ack floor
    "case_id": _STR,
    "applied": _BOOL,
    "disposition": _enum("released", "purged"),
    "verified_at": _STR,
}, required=["applied", "disposition"])

MARK_COMPLETED_INPUT = _input({"case_id": _STR})
MARK_COMPLETED_OUTPUT = _action_output({
    "case_id": _STR,
    "state": _enum("completed"),
}, required=["state"])

PURGE_WORKING_DATA_INPUT = _input({"case_id": _STR})
PURGE_WORKING_DATA_OUTPUT = _action_output({
    "case_id": _STR,
    "purged": _BOOL,
    "artifacts_removed": _INT,
}, required=["purged"])

# ============================ shared handback (action) ============================ #

NOTIFY_PEGA_INPUT = _input({
    "case_id": _STR,
    "segment": _STR,            # "A" | "B" | "C"
    "event": _STR,              # e.g. "CaseClosed"
    "result": {"type": "object"},  # agent-produced pass-through of the segment result (open by design)
})
NOTIFY_PEGA_OUTPUT = _action_output({
    "case_id": _STR,
    "event": _STR,
    "delivered": _BOOL,
    "target": _STR,
}, required=["delivered"])
