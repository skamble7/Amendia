# app/capabilities/wire_repair/draft_rfi.py
"""cap.payment.draft_rfi — draft a request-for-information (assist for ObtainInfo)."""
from __future__ import annotations

from typing import Any, Dict

ARTIFACT_KEY = "art.payment.rfi_request"


def run(*, inputs: Dict[str, Any], envelope: Dict[str, Any], mode: str = "execute",
        approved_action_ids=None) -> Dict[str, Any]:
    bic = envelope["payment"].get("creditor_agent", {}).get("bic", "UNKNOWNXX")
    rfi = {
        "recipient": {"party": "beneficiary_bank", "bic": bic},
        "channel": "camt.027",
        "questions": [
            "Please confirm the correct beneficiary account number.",
            "Confirm the beneficiary name and registered address.",
        ],
    }
    return {"outputs": {ARTIFACT_KEY: rfi}, "log": "drafted RFI to beneficiary bank"}
