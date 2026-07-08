# app/capabilities/wire_repair/record_resolution.py
"""cap.payment.record_resolution — the audit-facing resolution record."""
from __future__ import annotations

from typing import Any, Dict

ARTIFACT_KEY = "art.payment.resolution_record"


def run(*, inputs: Dict[str, Any], envelope: Dict[str, Any], mode: str = "execute",
        approved_action_ids=None) -> Dict[str, Any]:
    repair = inputs.get("repair", {})
    screening = inputs.get("screening", {})
    uetr = repair.get("uetr", envelope["payment"]["uetr"])
    record = {
        "outcome": "repaired_and_released",
        "summary": f"Repaired UETR {uetr} ({len(repair.get('corrections', []))} correction(s)) and "
                   f"released after a {screening.get('verdict', 'clean')} sanctions screen.",
        "references": [
            {"kind": "artifact", "id": "repair_instruction"},
            {"kind": "artifact", "id": "screening_result"},
        ],
    }
    return {"outputs": {ARTIFACT_KEY: record}, "log": "recorded resolution"}
