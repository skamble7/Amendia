# app/capabilities/wire_repair/apply_repair.py
"""cap.payment.apply_repair — side-effectful; propose then execute (post-approval).

Propose mode returns the actions a human must authorize (approve_actions gate).
Execute mode (after approval) performs the "apply" — SIMULATED, no real side
effects — and returns no artifact (the binding declares no outputs).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.capabilities.wire_repair._common import reason_codes
from app.engine.executor.base import CapabilityBusinessError

logger = logging.getLogger(__name__)


def run(*, inputs: Dict[str, Any], envelope: Dict[str, Any], mode: str = "execute",
        approved_action_ids=None) -> Dict[str, Any]:
    repair = inputs.get("repair", {})
    uetr = repair.get("uetr", envelope["payment"]["uetr"])
    if mode == "propose":
        n = len(repair.get("corrections", []))
        actions = [{
            "action_id": "act-apply-repair",
            "kind": "apply_repair",
            "summary": f"Apply {n} correction(s) to UETR {uetr} and release the payment",
            "detail": {"uetr": uetr, "corrections": repair.get("corrections", [])},
        }]
        return {"proposed_actions": actions, "log": "proposed apply_repair (no side effects)"}

    # ADR-030 (Phase 2.3): a rails-side reject of the repaired payment is a MODELED business error —
    # signal it so the runtime routes to the ApplyRepair "payment rejected" error boundary (a
    # return/rework path), NOT a technical failure. Steered by an "RJCT" reason code (sim only).
    if "RJCT" in reason_codes(envelope):
        raise CapabilityBusinessError("PAYMENT_REJECTED", detail={"uetr": uetr})
    # A plain exception is a TECHNICAL failure (not modeled) — it must NOT be caught by an error
    # boundary; the instance fails/retries as before (sim steer for the regression test).
    if "TECHFAIL" in reason_codes(envelope):
        raise RuntimeError("simulated rails timeout")

    logger.warning("SIMULATED apply_repair EXECUTED for UETR %s (no real payment side effect)", uetr)
    return {"outputs": {}, "log": f"SIMULATED apply_repair executed; UETR {uetr} released"}
