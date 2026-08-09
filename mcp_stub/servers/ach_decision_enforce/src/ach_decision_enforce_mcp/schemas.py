# schemas.py
"""Per-tool JSON Schemas (draft 2020-12) for the ACH-exposure **Enforce** segment MCP server.

Carried over verbatim from the combined ach_exposure server (ADR-063 split) — only this segment's tools plus the
shared ``notify_pega`` handback. §3.2: the Segment-B gateway branches on ``decision.rbo_decision``, so
``capture_decision``'s output is the contract (enum ``rbo_decision``, required). Action tools carry the ack floor.
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


# ============================ Segment B ============================ #

CAPTURE_DECISION_INPUT = _input({
    "case_id": _STR,
    "rbo_decision": _STR,       # "approve" | "reject" (from Pega's EnforceDecisionRequested trigger)
    "underwriter": _STR,
    "conditions": _STR,
    "decision": _typed_open({"rbo_decision": _STR, "underwriter": _STR, "conditions": _STR}),
})
# The artifact bound to this output is named `decision` at onboarding, so the Segment-B gateway condition
# `decision.rbo_decision = "approve"` resolves. Read-only (records a decision under SoD) — no ack floor.
CAPTURE_DECISION_OUTPUT = _output({
    "case_id": _STR,
    "rbo_decision": _enum("approve", "reject"),   # the gateway key — required
    "captured_by": _STR,
    "underwriter": _STR,
    "sod_satisfied": _BOOL,
    "decision_id": _STR,
}, required=["rbo_decision", "sod_satisfied"])

PREPARE_RELEASE_INPUT = _input({
    "case_id": _STR, "company": _STR, "records": _STR_ARR,
    "decision": _typed_open({"rbo_decision": _STR}),
})
PREPARE_RELEASE_OUTPUT = _action_output({
    "case_id": _STR,
    "instruction": _enum("release"),
    "marked_items": _INT,
    "release_ref": _STR,
}, required=["instruction"])

REQUEST_PURGE_INPUT = _input({
    "case_id": _STR, "company": _STR, "records": _STR_ARR, "reason": _STR,
    "decision": _typed_open({"rbo_decision": _STR}),
})
REQUEST_PURGE_OUTPUT = _action_output({
    "case_id": _STR,
    "instruction": _enum("purge"),
    "tma_ref": _STR,
    "fis_ticket": _STR,
}, required=["instruction"])

# ============================ shared handback (action) ============================ #

NOTIFY_PEGA_INPUT = _input({
    "case_id": _STR,
    "segment": _STR,            # "A" | "B" | "C"
    "event": _STR,              # e.g. "DecisionEnforced"
    "result": {"type": "object"},  # agent-produced pass-through of the segment result (open by design)
})
NOTIFY_PEGA_OUTPUT = _action_output({
    "case_id": _STR,
    "event": _STR,
    "delivered": _BOOL,
    "target": _STR,
}, required=["delivered"])
