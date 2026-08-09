# schemas.py
"""Per-tool JSON Schemas (draft 2020-12) for the ACH-exposure **Assess** segment MCP server.

Carried over verbatim from the combined ach_exposure server (ADR-063 split) — only this segment's tools plus the
shared ``notify_pega`` handback. Authored to the Amendia MCP Implementor Guideline
(`backend/docs/methodology/amendia_mcp_implementor_guideline.md`): root-object in/out schemas, no external
``$ref``, closed outputs, enum-typed decision fields, ack floor on action tools.
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


# --------------------------------------------------------------------------- #
# Common nested input shapes (typed-open pass-throughs)
# --------------------------------------------------------------------------- #
_CASE = _typed_open({"case_id": _STR, "company": _STR, "company_number": _STR, "batch_id": _STR})
_AMOUNTS = _typed_open({
    "exposure_type": _STR, "credit_amount": _NUM, "debit_amount": _NUM,
    "credit_limit": _NUM, "debit_limit": _NUM, "overage": _NUM,
})

# ============================ Segment A (read-only) ============================ #

CLASSIFY_EXPOSURE_INPUT = _input({
    "case_id": _STR, "exposure_type": _STR,
    "credit_amount": _NUM, "debit_amount": _NUM, "credit_limit": _NUM, "debit_limit": _NUM, "overage": _NUM,
    "exposure": _AMOUNTS,
})
CLASSIFY_EXPOSURE_OUTPUT = _output({
    "case_id": _STR,
    "exposure_class": _enum("credit", "debit"),
    "amount": _NUM,
    "limit": _NUM,
    "overage": _NUM,
    "severity": _enum("within_tolerance", "material", "severe"),
}, required=["exposure_class", "severity", "overage"])

CLIENT_RISK_PROFILE_INPUT = _input({
    "case_id": _STR, "company": _STR, "company_number": _STR, "case": _CASE,
})
CLIENT_RISK_PROFILE_OUTPUT = _output({
    "case_id": _STR,
    "company": _STR,
    "risk_tier": _enum("low", "medium", "high"),
    "standing": _enum("good", "watch"),
    "prior_exceptions": _INT,
    "temp_limit_active": _BOOL,
}, required=["risk_tier", "standing"])

RECOMMEND_DISPOSITION_INPUT = _input({
    "case_id": _STR,
    "exposure_class": _STR, "severity": _STR, "overage": _NUM,
    "risk_tier": _STR, "standing": _STR,
    "classification": _typed_open({"exposure_class": _STR, "severity": _STR, "overage": _NUM}),
    "risk_profile": _typed_open({"risk_tier": _STR, "standing": _STR}),
})
RECOMMEND_DISPOSITION_OUTPUT = _output({
    "case_id": _STR,
    "recommendation": _enum("APPROVE", "REJECT", "ROUTE_UW"),
    "confidence": _CONF,
    "rationale": _STR,
}, required=["recommendation", "confidence", "rationale"])

DRAFT_UNDERWRITING_INPUT = _input({
    "case_id": _STR, "company": _STR, "exposure_class": _STR, "overage": _NUM,
    "recommendation": _STR, "rationale": _STR,
})
DRAFT_UNDERWRITING_OUTPUT = _output({
    "case_id": _STR,
    "subject": _STR,
    "body": _STR,
}, required=["subject", "body"])

# ============================ shared handback (action) ============================ #

NOTIFY_PEGA_INPUT = _input({
    "case_id": _STR,
    "segment": _STR,            # "A" | "B" | "C"
    "event": _STR,              # e.g. "ExposureAssessed"
    "result": {"type": "object"},  # agent-produced pass-through of the segment result (open by design)
})
NOTIFY_PEGA_OUTPUT = _action_output({
    "case_id": _STR,
    "event": _STR,
    "delivered": _BOOL,
    "target": _STR,
}, required=["delivered"])
