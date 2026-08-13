# src/pega_stub/scenarios.py
"""The ACH-exposure case scenarios + the four envelope shapes the mock Pega submits.

Every envelope carries ``case_id`` at the top level — that is the cohort ``correlation_value``. Each segment
payload leads with a ``request_type`` — that is what each pack's triage rule matches on. The close payload
carries ``event: "process_completed"`` — that is what the cohort close schema recognises.
"""
from __future__ import annotations

from typing import Any, Dict

# request_type discriminators the segment packs' triage rules key on.
REQ_ASSESS = "AssessExposureRequested"
REQ_ENFORCE = "EnforceDecisionRequested"
REQ_CLOSEOUT = "CloseoutRequested"

# trigger_type (platform discriminator) + schema_version per message.
TRIGGER_TYPE = {
    "A": "ach.assess_exposure_requested",
    "B": "ach.enforce_decision_requested",
    "C": "ach.closeout_requested",
    "close": "ach.process_completed",
}
SCHEMA_VERSION = {
    "A": "pin.ach.assess_exposure/1.0",
    "B": "pin.ach.enforce_decision/1.0",
    "C": "pin.ach.closeout/1.0",
    "close": "pin.ach.process_completed/1.0",
}

DEFAULT_UNDERWRITER = "rbo.underwriter@flagstar.com"

# Per-scenario presets. `rbo_decision` is the hands-free default for Segment B (used when Segment A's
# recommendation is ROUTE_UW or absent); amounts are chosen to be plausible for each disposition.
SCENARIOS: Dict[str, Dict[str, Any]] = {
    "credit_approve": {
        "company": "ACME-LOGISTICS", "exposure_type": "credit",
        "credit_amount": 330000.0, "credit_limit": 300000.0, "debit_amount": 0.0, "debit_limit": 200000.0,
        "overage": 30000.0, "rbo_decision": "approve",
    },
    "debit_reject": {
        "company": "RIVERSIDE-TRUCKING", "exposure_type": "debit",
        "credit_amount": 0.0, "credit_limit": 300000.0, "debit_amount": 340000.0, "debit_limit": 200000.0,
        "overage": 140000.0, "rbo_decision": "reject",
    },
    "route_uw": {
        "company": "MIDCITY-RETAIL", "exposure_type": "credit",
        "credit_amount": 360000.0, "credit_limit": 300000.0, "debit_amount": 0.0, "debit_limit": 200000.0,
        "overage": 60000.0, "rbo_decision": "approve",
    },
    # ADR-064 SLA e2e: a normal approve case through A and B, but the Segment C (closeout) trigger is fired
    # LATE — past the cohort's enforce→closeout arrival SLA (20s) — so the SLA breaches (owner=external), the
    # closeout then arrives late (recorded `arrived_late`), and the case still closes. `closeout_delay_seconds`
    # is the opt-in delay; the other three presets omit it (absent/0 → fire immediately, unchanged).
    "late_closeout": {
        "company": "DELTA-FREIGHT", "exposure_type": "credit",
        "credit_amount": 335000.0, "credit_limit": 300000.0, "debit_amount": 0.0, "debit_limit": 200000.0,
        "overage": 35000.0, "rbo_decision": "approve",
        "closeout_delay_seconds": 25,   # > the 20s enforce→closeout arrival SLA → breach, then late arrival
    },
}


def segment_a_payload(case_id: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "request_type": REQ_ASSESS, "case_id": case_id, "company": scenario["company"],
        "exposure_type": scenario["exposure_type"], "credit_amount": scenario["credit_amount"],
        "credit_limit": scenario["credit_limit"], "debit_amount": scenario["debit_amount"],
        "debit_limit": scenario["debit_limit"], "overage": scenario["overage"],
    }


def segment_b_payload(case_id: str, rbo_decision: str, underwriter: str = DEFAULT_UNDERWRITER) -> Dict[str, Any]:
    return {"request_type": REQ_ENFORCE, "case_id": case_id, "rbo_decision": rbo_decision, "underwriter": underwriter}


def segment_c_payload(case_id: str, instruction: str) -> Dict[str, Any]:
    return {"request_type": REQ_CLOSEOUT, "case_id": case_id, "instruction": instruction}


def close_payload(case_id: str, outcome: str) -> Dict[str, Any]:
    return {"event": "process_completed", "case_id": case_id, "outcome": outcome}


# The cohort definition's close schema — this is what the operator registers (or the flagged self-register
# helper posts). It must match `close_payload` above; correlation path is `case_id`, outcome path `outcome`.
COHORT_CLOSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["event", "case_id"],
    "properties": {
        "event": {"const": "process_completed"},
        "case_id": {"type": "string"},
        "outcome": {"type": "string"},
    },
}
