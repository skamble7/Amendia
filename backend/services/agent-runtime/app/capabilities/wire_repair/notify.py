# app/capabilities/wire_repair/notify.py
"""cap.payment.notify_parties — side-effectful; propose then execute (post-approval)."""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def run(*, inputs: Dict[str, Any], envelope: Dict[str, Any], mode: str = "execute",
        approved_action_ids=None) -> Dict[str, Any]:
    uetr = envelope["payment"]["uetr"]
    if mode == "propose":
        actions = [{
            "action_id": "act-notify-originator",
            "kind": "notify_parties",
            "summary": "Notify the originator and beneficiary bank of the repair & release",
            "detail": {"uetr": uetr, "advices": ["camt.998", "MT199"]},
        }]
        return {"proposed_actions": actions, "log": "proposed notify_parties (no side effects)"}

    logger.warning("SIMULATED notify_parties SENT for UETR %s (no real messages)", uetr)
    return {"outputs": {}, "log": f"SIMULATED notify_parties sent for UETR {uetr}"}
