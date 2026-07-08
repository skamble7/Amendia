# app/capabilities/wire_repair/assess.py
"""cap.payment.assess_beneficiary — repairability verdict from the reason code.

AC01/AC04 → repairable with a proposed account correction; RC01 → repairable
(agent BIC); BE04 → needs_info (drives the ObtainInfo path); anything else →
needs_info. Confidence/rationale/evidence are filled plausibly.
"""
from __future__ import annotations

from typing import Any, Dict

from app.capabilities.wire_repair._common import correct_account, drop_none, reason_codes

ARTIFACT_KEY = "art.payment.repair_verdict"


def run(*, inputs: Dict[str, Any], envelope: Dict[str, Any], mode: str = "execute",
        approved_action_ids=None) -> Dict[str, Any]:
    codes = reason_codes(envelope)
    p = envelope["payment"]
    creditor = p.get("creditor", {})
    acct = (creditor.get("account") or {}).get("id", "")

    if "BE04" in codes:
        verdict = {
            "repair_verdict": "needs_info",
            "confidence": 0.42,
            "rationale": "Beneficiary name/address mismatch (BE04); insufficient information to repair.",
            "evidence": [{"kind": "name_match", "detail": "partial creditor name match"}],
        }
    elif any(c in codes for c in ("AC01", "AC04")):
        verdict = {
            "repair_verdict": "repairable",
            "confidence": 0.91,
            "rationale": "Creditor account invalid/closed (AC01/AC04); corrected via digit-transposition "
                         "check against prior settlement history.",
            "proposed_correction": {
                "field": "creditor.account.id",
                "current_value": acct,
                "proposed_value": correct_account(acct),
            },
            "evidence": [{"kind": "history", "detail": "prior settlement to the corrected account"}],
        }
    elif "RC01" in codes:
        bic = p.get("creditor_agent", {}).get("bic", "")
        verdict = {
            "repair_verdict": "repairable",
            "confidence": 0.83,
            "rationale": "Bank identifier incorrect (RC01); correctable from the BIC directory.",
            "proposed_correction": {
                "field": "creditor_agent.bic",
                "current_value": bic,
                "proposed_value": bic,
            },
            "evidence": [{"kind": "correspondence", "detail": "BIC directory lookup"}],
        }
    else:
        verdict = {
            "repair_verdict": "needs_info",
            "confidence": 0.30,
            "rationale": "Unrecognized reason code; request more information.",
            "evidence": [{"kind": "history", "detail": "no matching pattern"}],
        }

    return {"outputs": {ARTIFACT_KEY: drop_none(verdict)}, "log": f"assessed repairability: {verdict['repair_verdict']}"}
