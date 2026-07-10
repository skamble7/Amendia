# tests/_wire.py
"""Shared helpers for driving the compiled wire-repair graph in tests."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from langgraph.types import Command

ROLE_USER = {
    "role.payments.ops_analyst": "analyst-1",
    "role.payments.ops_approver": "approver-1",
}


def role_user(role: Optional[str]) -> str:
    return ROLE_USER.get(role or "", "user-x")


def make_envelope(
    reason_code: str = "AC01",
    *,
    exception_id: str = "EXC-2026-000999",
    creditor_name: str = "ACME BENEFICIARY LLC",
    account_id: str = "GB29NWBK60161331926819",
) -> Dict[str, Any]:
    return {
        "exception_id": exception_id,
        "source": {"system": "pacs-gateway", "channel": "swift"},
        "received_at": "2026-07-07T10:00:00Z",
        "exception_type": "unable_to_apply",
        "reason_codes": [reason_code],
        "reason_narrative": f"Unable to apply payment ({reason_code}).",
        "status": "open",
        "payment": {
            "msg_type": "pacs.008.001.10",
            "uetr": "97ed4827-7b6f-4491-a06f-b548d5a7512d",
            "instruction_id": "INSTR-1",
            "end_to_end_id": "E2E-1",
            "settlement_amount": {"currency": "USD", "value": 250000.0},
            "value_date": "2026-07-06",
            "debtor": {"name": "ORIGINATOR CORP"},
            "debtor_agent": {"bic": "CHASUS33"},
            "creditor": {"name": creditor_name, "account": {"id": account_id, "scheme": "IBAN"}},
            "creditor_agent": {"bic": "NWBKGB2L"},
            "charges": "SHA",
        },
        "related_messages": [],
        "attachments": [{
            "attachment_id": "att-1", "name": "camt026.xml",
            "media_type": "application/xml", "sha256": "0" * 64,
            "fetch_url": "http://stub/exceptions/x/attachments/att-1",
        }],
    }


def default_decision(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Approve-positive decision for a gate, choosing the user by the gate's role."""
    mode = payload["hitl_mode"]
    user = role_user(payload.get("role"))
    decision = "complete" if mode == "manual" else "approve"
    return {"decision": decision, "decided_by": user}


def drive(
    app,
    config: Dict[str, Any],
    initial: Dict[str, Any],
    *,
    decide: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    max_steps: int = 60,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Run to completion, auto-resolving each interrupt. Returns (final_state, gates)."""
    decide = decide or default_decision
    gates: List[Dict[str, Any]] = []
    result = app.invoke(initial, config)
    steps = 0
    while "__interrupt__" in result:
        steps += 1
        if steps > max_steps:
            raise AssertionError("drive exceeded max_steps (possible loop)")
        payload = result["__interrupt__"][0].value
        gates.append(payload)
        result = app.invoke(Command(resume=decide(payload)), config)
    return result, gates


def run_to_first_gate(app, config, initial) -> Dict[str, Any]:
    """Run until the first interrupt and return its payload (no resume)."""
    result = app.invoke(initial, config)
    assert "__interrupt__" in result, f"expected an interrupt, got {list(result)}"
    return result["__interrupt__"][0].value
