# app/capabilities/wire_repair/sanctions.py
"""cap.payment.sanctions_screen — clean unless the creditor name carries a test marker.

Simulates the MCP sanctions-screening tool. A creditor name containing
``SANCTIONED`` returns a ``hit`` (exercises the rejection path in tests).
"""
from __future__ import annotations

from typing import Any, Dict

ARTIFACT_KEY = "art.compliance.screening_result"

SANCTION_MARKER = "SANCTIONED"


def run(*, inputs: Dict[str, Any], envelope: Dict[str, Any], mode: str = "execute",
        approved_action_ids=None) -> Dict[str, Any]:
    creditor_name = envelope["payment"].get("creditor", {}).get("name", "")
    hit = SANCTION_MARKER in creditor_name.upper()
    verdict = "hit" if hit else "clean"
    screening = {
        "verdict": verdict,
        "party_results": [{
            "party": "creditor",
            "name": creditor_name,
            "result": verdict,
            "score": 0.97 if hit else 0.01,
        }],
        "list_refs": ["OFAC-SDN", "EU-CFSP"],
    }
    return {"outputs": {ARTIFACT_KEY: screening}, "log": f"sanctions screen: {verdict}"}
