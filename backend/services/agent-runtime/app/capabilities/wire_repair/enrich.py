# app/capabilities/wire_repair/enrich.py
"""cap.payment.enrich_investigation — build the investigation dossier from the envelope."""
from __future__ import annotations

from typing import Any, Dict

from app.capabilities.wire_repair._common import drop_none

ARTIFACT_KEY = "art.payment.investigation_dossier"


def run(*, inputs: Dict[str, Any], envelope: Dict[str, Any], mode: str = "execute",
        approved_action_ids=None) -> Dict[str, Any]:
    p = envelope["payment"]
    creditor = p.get("creditor", {})
    creditor_acct = (creditor.get("account") or {}).get("id")
    dossier = drop_none({
        "payment_snapshot": {
            "uetr": p["uetr"],
            "instruction_id": p.get("instruction_id"),
            "settlement_amount": {
                "currency": p["settlement_amount"]["currency"],
                "value": p["settlement_amount"]["value"],
            },
            "debtor_name": p.get("debtor", {}).get("name"),
            "creditor": {
                "name": creditor.get("name", ""),
                "account_id": creditor_acct,
                "agent_bic": p.get("creditor_agent", {}).get("bic"),
            },
        },
        "gpi_status": {
            "status": "stopped_at_beneficiary",
            "last_update": envelope.get("received_at"),
        },
        "attachment_summaries": [
            {
                "attachment_id": a["attachment_id"],
                "media_type": a["media_type"],
                "summary": f"{a.get('name', a['attachment_id'])} (present; bytes not fetched)",
            }
            for a in envelope.get("attachments", []) or []
        ],
    })
    return {"outputs": {ARTIFACT_KEY: dossier}, "log": "enriched investigation dossier from envelope"}
