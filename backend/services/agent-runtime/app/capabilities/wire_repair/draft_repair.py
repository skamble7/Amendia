# app/capabilities/wire_repair/draft_repair.py
"""cap.payment.draft_repair — turn the verdict's proposed_correction into a repair instruction."""
from __future__ import annotations

from typing import Any, Dict

ARTIFACT_KEY = "art.payment.repair_instruction"


def run(*, inputs: Dict[str, Any], envelope: Dict[str, Any], mode: str = "execute",
        approved_action_ids=None) -> Dict[str, Any]:
    beneficiary = inputs.get("beneficiary", {})
    pc = beneficiary.get("proposed_correction")
    uetr = envelope["payment"]["uetr"]
    if pc:
        corrections = [{
            "field": pc.get("field", "creditor.account.id"),
            "before": pc.get("current_value", ""),
            "after": pc.get("proposed_value", ""),
        }]
    else:
        creditor = envelope["payment"].get("creditor", {})
        acct = (creditor.get("account") or {}).get("id", "")
        corrections = [{"field": "creditor.account.id", "before": acct, "after": acct}]
    repair = {
        "uetr": uetr,
        "corrections": corrections,
        "justification": beneficiary.get("rationale", "Repair derived from repairability verdict."),
        "requires_rescreen": True,
    }
    return {"outputs": {ARTIFACT_KEY: repair}, "log": "drafted repair instruction"}
