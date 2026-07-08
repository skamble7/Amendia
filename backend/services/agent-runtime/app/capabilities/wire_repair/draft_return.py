# app/capabilities/wire_repair/draft_return.py
"""cap.payment.draft_return — a pacs.004-shaped return instruction."""
from __future__ import annotations

from typing import Any, Dict

from app.capabilities.wire_repair._common import reason_codes

ARTIFACT_KEY = "art.payment.return_instruction"

_KNOWN = ("AC01", "AC04", "RC01", "BE04")


def run(*, inputs: Dict[str, Any], envelope: Dict[str, Any], mode: str = "execute",
        approved_action_ids=None) -> Dict[str, Any]:
    p = envelope["payment"]
    code = next((c for c in reason_codes(envelope) if c in _KNOWN), "AC04")
    beneficiary = inputs.get("beneficiary", {})
    ret = {
        "uetr": p["uetr"],
        "return_reason_code": code,
        "returned_amount": {
            "currency": p["settlement_amount"]["currency"],
            "value": p["settlement_amount"]["value"],
        },
        "narrative": beneficiary.get("rationale", "Unable to repair the beneficiary details; returning funds."),
    }
    return {"outputs": {ARTIFACT_KEY: ret}, "log": f"drafted return (reason {code})"}
