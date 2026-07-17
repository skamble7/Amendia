# schemas.py
"""Per-tool JSON Schemas (draft 2020-12) for the wire-transfer-exception MCP server.

These are the contract. The process-registry onboarding wizard
(``POST /capabilities/introspect-mcp``, ADR-025) turns each tool's ``inputSchema`` and
``outputSchema`` into two artifact schemas + one ``kind: mcp`` capability, and the pack's
exclusive gateway branches on ``beneficiary.repair_verdict`` — so the **output** shapes here
must match the spec exactly.

Design rules (mirroring what the wizard enforces in
``process-registry/app/services/mcp_introspect.py``):
- root ``type: object`` on every schema;
- no external ``$ref`` (schemas are fully self-contained);
- **outputs are closed** (``additionalProperties: false`` recursively) — they're the
  contract the artifacts + gateway depend on;
- **inputs are permissive** — root is closed, but each carries an *open* payload object so a
  caller can pass a whole ``dossier`` / ``repair`` / ``envelope`` without being rejected.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

DRAFT = "https://json-schema.org/draft/2020-12/schema"


# --------------------------------------------------------------------------- #
# Small builders
# --------------------------------------------------------------------------- #

def _closed(properties: Dict[str, Any], *, required: Iterable[str] = ()) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": properties}
    if required:
        schema["required"] = list(required)
    return schema


def _open() -> Dict[str, Any]:
    """A permissive nested object — a caller may pass any structure inside it."""
    return {"type": "object"}


def _arr(items: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "array", "items": items}


_STR = {"type": "string"}
_NUM = {"type": "number"}
_BOOL = {"type": "boolean"}
_STR_ARR = {"type": "array", "items": {"type": "string"}}


def _input(properties: Dict[str, Any]) -> Dict[str, Any]:
    """A permissive input: root object, closed at the top level (only the declared payload
    props), but the payload objects themselves are open. No required fields — the dumb
    handlers tolerate whatever they get."""
    return {"$schema": DRAFT, "type": "object", "additionalProperties": False, "properties": properties}


def _output(properties: Dict[str, Any], required: Iterable[str]) -> Dict[str, Any]:
    return {"$schema": DRAFT, "type": "object", "additionalProperties": False,
            "properties": properties, "required": list(required)}


def _ack_output(extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """The guideline acknowledgement shape shared by the three side-effectful action tools."""
    props: Dict[str, Any] = {
        "acknowledged": _BOOL,
        "action_id": _STR,
        "status": {"type": "string", "enum": ["performed", "queued", "rejected"]},
    }
    if extra:
        props.update(extra)
    return _output(props, required=["acknowledged", "action_id", "status"])


# --------------------------------------------------------------------------- #
# Enums referenced by the pack / gateway
# --------------------------------------------------------------------------- #

REPAIR_VERDICTS = ["repairable", "unrepairable", "needs_info"]
SCREENING_STATUSES = ["clear", "hit", "needs_review"]


# --------------------------------------------------------------------------- #
# 1) enrich_investigation
# --------------------------------------------------------------------------- #

ENRICH_INPUT = _input({
    "envelope": _open(),
    "exception_id": _STR,
    "reason_codes": _STR_ARR,
})

ENRICH_OUTPUT = _output(
    {
        "exception_id": _STR,
        "payment": _closed({
            "msg_type": _STR,
            "amount": _NUM,
            "currency": _STR,
            "creditor": _STR,
            "debtor": _STR,
        }),
        "parties": _arr(_closed({"role": _STR, "name": _STR, "account": _STR})),
        "history": _arr(_closed({"ts": _STR, "event": _STR})),
    },
    required=["exception_id"],
)


# --------------------------------------------------------------------------- #
# 2) assess_beneficiary
# --------------------------------------------------------------------------- #

ASSESS_INPUT = _input({
    "dossier": _open(),
    "exception_id": _STR,
    "repair_hint": {"type": "string", "enum": REPAIR_VERDICTS},
    "reason_codes": _STR_ARR,
})

ASSESS_OUTPUT = _output(
    {
        "repair_verdict": {"type": "string", "enum": REPAIR_VERDICTS},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": _STR,
    },
    required=["repair_verdict", "rationale"],  # gateway reads beneficiary.repair_verdict — MUST be required
)


# --------------------------------------------------------------------------- #
# 3) draft_rfi
# --------------------------------------------------------------------------- #

RFI_INPUT = _input({"dossier": _open(), "exception_id": _STR, "missing_fields": _STR_ARR})

RFI_OUTPUT = _output({"message": _STR, "missing_fields": _STR_ARR}, required=["message"])


# --------------------------------------------------------------------------- #
# 4) draft_repair
# --------------------------------------------------------------------------- #

DRAFT_REPAIR_INPUT = _input({"dossier": _open(), "verdict": _open(), "exception_id": _STR})

DRAFT_REPAIR_OUTPUT = _output(
    {"field": _STR, "current_value": _STR, "proposed_value": _STR, "justification": _STR},
    required=["field", "proposed_value"],
)


# --------------------------------------------------------------------------- #
# 5) screen_party
# --------------------------------------------------------------------------- #

SCREEN_INPUT = _input({"party": _open(), "envelope": _open(), "exception_id": _STR, "hint": _STR})

SCREEN_OUTPUT = _output(
    {
        "status": {"type": "string", "enum": SCREENING_STATUSES},
        "matched_lists": _STR_ARR,
        "score": {"type": "number", "minimum": 0, "maximum": 1},
    },
    required=["status"],
)


# --------------------------------------------------------------------------- #
# 6) apply_repair (side-effectful)
# --------------------------------------------------------------------------- #

APPLY_REPAIR_INPUT = _input({"repair": _open(), "exception_id": _STR})

APPLY_REPAIR_OUTPUT = _ack_output({"release_ref": _STR, "performed_at": _STR})


# --------------------------------------------------------------------------- #
# 7) notify_parties (side-effectful)
# --------------------------------------------------------------------------- #

NOTIFY_INPUT = _input({"resolution": _open(), "exception_id": _STR, "recipients": _STR_ARR})

NOTIFY_OUTPUT = _ack_output({"message_ids": _STR_ARR, "performed_at": _STR})


# --------------------------------------------------------------------------- #
# 8) record_resolution
# --------------------------------------------------------------------------- #

RECORD_INPUT = _input({"dossier": _open(), "exception_id": _STR, "evidence": _arr(_open())})

RECORD_OUTPUT = _output(
    {
        "summary": _STR,
        "evidence": _arr(_closed({"kind": _STR, "detail": _STR})),
        "resolved_at": _STR,
    },
    required=["summary"],
)


# --------------------------------------------------------------------------- #
# 9) draft_return
# --------------------------------------------------------------------------- #

DRAFT_RETURN_INPUT = _input({"dossier": _open(), "exception_id": _STR, "reason_codes": _STR_ARR})

DRAFT_RETURN_OUTPUT = _output(
    {"return_reason_code": _STR, "pacs004_ref": _STR, "amount": _NUM, "currency": _STR},
    required=["return_reason_code"],
)


# --------------------------------------------------------------------------- #
# 10) execute_return (side-effectful)
# --------------------------------------------------------------------------- #

EXECUTE_RETURN_INPUT = _input({"return_instruction": _open(), "exception_id": _STR})

EXECUTE_RETURN_OUTPUT = _ack_output({"return_ref": _STR, "performed_at": _STR})
