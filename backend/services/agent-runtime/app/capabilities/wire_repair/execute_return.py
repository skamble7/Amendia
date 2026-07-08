# app/capabilities/wire_repair/execute_return.py
"""cap.payment.execute_return — side-effectful; propose then execute (post-approval)."""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def run(*, inputs: Dict[str, Any], envelope: Dict[str, Any], mode: str = "execute",
        approved_action_ids=None) -> Dict[str, Any]:
    ret = inputs.get("return", {})
    uetr = ret.get("uetr", envelope["payment"]["uetr"])
    if mode == "propose":
        actions = [{
            "action_id": "act-execute-return",
            "kind": "execute_return",
            "summary": f"Execute the pacs.004 return of UETR {uetr} and notify the parties",
            "detail": {"uetr": uetr, "return_reason_code": ret.get("return_reason_code", "AC04")},
        }]
        return {"proposed_actions": actions, "log": "proposed execute_return (no side effects)"}

    logger.warning("SIMULATED execute_return EXECUTED for UETR %s (no real return)", uetr)
    return {"outputs": {}, "log": f"SIMULATED execute_return executed; UETR {uetr} returned"}
