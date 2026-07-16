# handlers.py
"""Dumb, deterministic tool handlers + the tool registry + the compliance self-check.

Every handler is a pure function of its arguments — no clock, no randomness, no network — so
the same input always yields the same output (including ``action_id``). Handlers echo salient
input fields into their outputs so a human reviewing a HITL task sees plausible, connected data.

This module does **not** import the ``mcp`` SDK, so the schemas, handlers, and compliance
self-check are testable without it (``server.py`` is the only place the SDK is used).
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Dict, List

from . import external as ext
from . import schemas as S

# A fixed, deterministic timestamp used when the input carries none — keeps outputs stable.
_FIXED_TS = "2025-01-01T00:00:00Z"

ACTION_TOOLS = {"apply_repair", "notify_parties", "execute_return"}

# Reason-code steering for assess_beneficiary (lets the demo drive each gateway branch).
_REPAIRABLE_CODES = {"AC01", "AC03", "INCORRECT_ACCOUNT", "RQ01"}
_UNREPAIRABLE_CODES = {"AC04", "AC06", "RC01", "CLOSED_ACCOUNT", "BLOCKED"}


# --------------------------------------------------------------------------- #
# Input digging (permissive — accept fields at the top level or inside a payload object)
# --------------------------------------------------------------------------- #

def _payload(args: Dict[str, Any], *names: str) -> Dict[str, Any]:
    for n in names:
        v = args.get(n)
        if isinstance(v, dict):
            return v
    return {}


def _dig(args: Dict[str, Any], key: str, default: Any = None) -> Any:
    """Find ``key`` at the top level or one level down inside any payload object."""
    if key in args and args[key] is not None:
        return args[key]
    for v in args.values():
        if isinstance(v, dict) and v.get(key) is not None:
            return v[key]
    return default


def _name(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("name") or "")
    return str(v) if v is not None else ""


def _num(v: Any, default: float = 0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _reason_codes(args: Dict[str, Any]) -> List[str]:
    codes = _dig(args, "reason_codes", [])
    return [str(c).upper() for c in codes] if isinstance(codes, list) else []


def exception_id(args: Dict[str, Any]) -> str:
    return str(_dig(args, "exception_id", "unknown-exception"))


def action_id(tool: str, exc_id: str) -> str:
    """Deterministic, idempotent, auditable — a hash of the exception id + tool name."""
    return "act-" + hashlib.sha256(f"{tool}:{exc_id}".encode("utf-8")).hexdigest()[:16]


def _ts(args: Dict[str, Any]) -> str:
    return str(_dig(args, "occurred_at", None) or _dig(args, "as_of", None) or _FIXED_TS)


# --------------------------------------------------------------------------- #
# Read-only handlers
# --------------------------------------------------------------------------- #

def enrich_investigation(args: Dict[str, Any]) -> Dict[str, Any]:
    exc = exception_id(args)
    env = _payload(args, "envelope")
    pay = env.get("payment") if isinstance(env.get("payment"), dict) else env
    creditor, debtor = _name(pay.get("creditor")), _name(pay.get("debtor"))
    ext.fetch_payment(exc)  # "Core Banking" lookup (deterministic; realism only)
    return {
        "exception_id": exc,
        "payment": {
            "msg_type": str(pay.get("msg_type") or "pacs.008"),
            "amount": _num(pay.get("amount"), 125000.0),
            "currency": str(pay.get("currency") or "USD"),
            "creditor": creditor or "ACME BENEFICIARY LTD",
            "debtor": debtor or "ORIGINATOR CORP",
        },
        "parties": [
            {"role": "creditor", "name": creditor or "ACME BENEFICIARY LTD", "account": str(pay.get("creditor_account") or "DE00 0000 0000")},
            {"role": "debtor", "name": debtor or "ORIGINATOR CORP", "account": str(pay.get("debtor_account") or "GB00 0000 0000")},
        ],
        "history": [
            {"ts": _ts(args), "event": f"exception {exc} received"},
            {"ts": _ts(args), "event": "payment fetched from core banking"},
        ],
    }


def assess_beneficiary(args: Dict[str, Any]) -> Dict[str, Any]:
    hint = _dig(args, "repair_hint")
    codes = set(_reason_codes(args))
    if hint in S.REPAIR_VERDICTS:
        verdict = hint
        rationale = f"steered by repair_hint='{hint}'"
    elif codes & _UNREPAIRABLE_CODES:
        verdict = "unrepairable"
        rationale = f"reason codes {sorted(codes & _UNREPAIRABLE_CODES)} indicate the payment cannot be repaired"
    elif codes & _REPAIRABLE_CODES:
        verdict = "repairable"
        rationale = f"reason codes {sorted(codes & _REPAIRABLE_CODES)} are correctable via a repair instruction"
    else:
        verdict = "needs_info"
        rationale = "insufficient information to decide repairability; request more detail"
    confidence = {"repairable": 0.88, "unrepairable": 0.82, "needs_info": 0.4}[verdict]
    return {"repair_verdict": verdict, "confidence": confidence, "rationale": rationale}


def draft_rfi(args: Dict[str, Any]) -> Dict[str, Any]:
    exc = exception_id(args)
    missing = _dig(args, "missing_fields", []) or ["beneficiary_account", "beneficiary_name"]
    missing = [str(m) for m in missing] if isinstance(missing, list) else [str(missing)]
    return {
        "message": f"Regarding exception {exc}: please provide the missing details ({', '.join(missing)}) "
                   f"so we can complete the wire repair.",
        "missing_fields": missing,
    }


def draft_repair(args: Dict[str, Any]) -> Dict[str, Any]:
    dossier = _payload(args, "dossier", "verdict")
    field = str(_dig(args, "field", None) or dossier.get("field") or "creditor_account")
    current = str(_dig(args, "current_value", None) or "DE00 0000 0000")
    proposed = str(_dig(args, "proposed_value", None) or "DE89 3704 0044 0532 0130 00")
    return {
        "field": field,
        "current_value": current,
        "proposed_value": proposed,
        "justification": f"Corrected '{field}' from the beneficiary bank's confirmation to enable release.",
    }


def screen_party(args: Dict[str, Any]) -> Dict[str, Any]:
    hint = _dig(args, "hint")
    party = _payload(args, "party", "envelope")
    name = _name(party.get("creditor") or party.get("name") or party)
    if hint in S.SCREENING_STATUSES:
        status = hint
    elif "SANCTIONED" in name.upper():
        status = "hit"
    else:
        status = "clear"
    matched = ["OFAC-SDN", "EU-CFSP"] if status == "hit" else ([] if status == "clear" else ["OFAC-SDN"])
    score = {"hit": 0.97, "needs_review": 0.6, "clear": 0.01}[status]
    return {"status": status, "matched_lists": matched, "score": score}


def record_resolution(args: Dict[str, Any]) -> Dict[str, Any]:
    exc = exception_id(args)
    return {
        "summary": f"Exception {exc} resolved; repair applied and payment released.",
        "evidence": [
            {"kind": "repair_instruction", "detail": "creditor_account corrected"},
            {"kind": "release", "detail": ext.post_payment_release(exc)},
        ],
        "resolved_at": _ts(args),
    }


def draft_return(args: Dict[str, Any]) -> Dict[str, Any]:
    exc = exception_id(args)
    dossier = _payload(args, "dossier")
    pay = dossier.get("payment") if isinstance(dossier.get("payment"), dict) else dossier
    return {
        "return_reason_code": str(_dig(args, "return_reason_code", None) or "AC04"),
        "pacs004_ref": ext.send_pacs004(exc),
        "amount": _num(pay.get("amount"), 125000.0),
        "currency": str(pay.get("currency") or "USD"),
    }


# --------------------------------------------------------------------------- #
# Side-effectful action handlers (return the guideline acknowledgement)
# --------------------------------------------------------------------------- #

def apply_repair(args: Dict[str, Any]) -> Dict[str, Any]:
    exc = exception_id(args)
    return {
        "acknowledged": True,
        "action_id": action_id("apply_repair", exc),
        "status": "performed",
        "release_ref": ext.post_payment_release(exc),
        "performed_at": _ts(args),
    }


def notify_parties(args: Dict[str, Any]) -> Dict[str, Any]:
    exc = exception_id(args)
    return {
        "acknowledged": True,
        "action_id": action_id("notify_parties", exc),
        "status": "performed",
        "message_ids": [ext.send_pacs008(exc)],
        "performed_at": _ts(args),
    }


def execute_return(args: Dict[str, Any]) -> Dict[str, Any]:
    exc = exception_id(args)
    return {
        "acknowledged": True,
        "action_id": action_id("execute_return", exc),
        "status": "performed",
        "return_ref": ext.post_return(exc),
        "performed_at": _ts(args),
    }


# --------------------------------------------------------------------------- #
# The tool registry — the 10 capability tools the wizard onboards.
# --------------------------------------------------------------------------- #

class ToolSpec(dict):
    """A plain dict with attribute access, for readability at call sites."""

    def __getattr__(self, k: str) -> Any:  # pragma: no cover - convenience
        return self[k]


def _spec(name, description, side_effect, input_schema, output_schema, handler) -> ToolSpec:
    return ToolSpec(name=name, description=description, side_effect=side_effect,
                    input_schema=input_schema, output_schema=output_schema, handler=handler)


TOOLS: List[ToolSpec] = [
    _spec("enrich_investigation", "Enrich and investigate a wire-transfer exception; returns an investigation dossier.",
          "read_only", S.ENRICH_INPUT, S.ENRICH_OUTPUT, enrich_investigation),
    _spec("assess_beneficiary", "Assess whether the beneficiary payment is repairable; returns a repair verdict.",
          "read_only", S.ASSESS_INPUT, S.ASSESS_OUTPUT, assess_beneficiary),
    _spec("draft_rfi", "Draft a request-for-information message for the missing fields.",
          "read_only", S.RFI_INPUT, S.RFI_OUTPUT, draft_rfi),
    _spec("draft_repair", "Draft a repair instruction (field correction) for the payment.",
          "read_only", S.DRAFT_REPAIR_INPUT, S.DRAFT_REPAIR_OUTPUT, draft_repair),
    _spec("screen_party", "Sanctions/compliance screen a party; returns a screening result.",
          "read_only", S.SCREEN_INPUT, S.SCREEN_OUTPUT, screen_party),
    _spec("apply_repair", "Apply the approved repair and release the payment (side-effectful).",
          "side_effectful", S.APPLY_REPAIR_INPUT, S.APPLY_REPAIR_OUTPUT, apply_repair),
    _spec("notify_parties", "Notify the originator and beneficiary bank of the outcome (side-effectful).",
          "side_effectful", S.NOTIFY_INPUT, S.NOTIFY_OUTPUT, notify_parties),
    _spec("record_resolution", "Record the resolution and supporting evidence.",
          "read_only", S.RECORD_INPUT, S.RECORD_OUTPUT, record_resolution),
    _spec("draft_return", "Draft a payment return (pacs.004) instruction.",
          "read_only", S.DRAFT_RETURN_INPUT, S.DRAFT_RETURN_OUTPUT, draft_return),
    _spec("execute_return", "Execute the approved return and notify (side-effectful).",
          "side_effectful", S.EXECUTE_RETURN_INPUT, S.EXECUTE_RETURN_OUTPUT, execute_return),
]

TOOLS_BY_NAME: Dict[str, ToolSpec] = {t["name"]: t for t in TOOLS}


# --------------------------------------------------------------------------- #
# Compliance self-check — the exact properties the onboarding wizard enforces
# (process-registry/app/services/mcp_introspect.py), asserted at import time so the
# server refuses to start non-compliant.
# --------------------------------------------------------------------------- #

def _iter_objects(schema: Any):
    """Yield every sub-schema that describes an object (has type 'object' or 'properties')."""
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            yield schema
        for v in schema.values():
            yield from _iter_objects(v)
    elif isinstance(schema, list):
        for item in schema:
            yield from _iter_objects(item)


def _has_ref(schema: Any) -> bool:
    if isinstance(schema, dict):
        if "$ref" in schema:
            return True
        return any(_has_ref(v) for v in schema.values())
    if isinstance(schema, list):
        return any(_has_ref(i) for i in schema)
    return False


def check_compliance(tools: List[ToolSpec] = TOOLS) -> None:
    """Assert every capability tool is Amendia-MCP-compliant. Raises ``AssertionError``
    (with the offending tool + reason) on the first violation."""
    assert len(tools) == 10, f"expected 10 capability tools, found {len(tools)}"
    for t in tools:
        n = t["name"]
        insch, outsch = t["input_schema"], t["output_schema"]
        # both schemas present, root type object
        assert isinstance(insch, dict) and insch.get("type") == "object", f"{n}: inputSchema root must be object"
        assert isinstance(outsch, dict) and outsch.get("type") == "object", f"{n}: outputSchema root must be object"
        # no external (any) $ref — schemas are self-contained
        assert not _has_ref(insch), f"{n}: inputSchema must not use $ref"
        assert not _has_ref(outsch), f"{n}: outputSchema must not use $ref"
        # input root is closed; output objects are all closed (the contract shapes)
        assert insch.get("additionalProperties") is False, f"{n}: inputSchema root must set additionalProperties:false"
        for obj in _iter_objects(outsch):
            assert obj.get("additionalProperties") is False, f"{n}: every output object must set additionalProperties:false"
        # side-effectful action tools carry the acknowledgement fields
        if t["side_effect"] == "side_effectful":
            req = set(outsch.get("required", []))
            assert {"acknowledged", "action_id", "status"} <= req, \
                f"{n}: action tool output must require acknowledged + action_id + status"


# Fail fast at import if anything drifts out of compliance.
check_compliance()
