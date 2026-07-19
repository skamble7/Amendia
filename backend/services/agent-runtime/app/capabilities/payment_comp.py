# app/capabilities/payment_comp.py
"""Side-effectful payment steps + their undo handlers for the ADR-043 compensation demo pack.

Each is a normal ``approve_actions`` capability: ``propose`` returns the action a human authorizes (no
side effect), ``execute`` performs the SIMULATED side effect (no real payment movement). The two undo
capabilities (``reverse_*``) are the compensation handlers — they reverse a prior release/debit; the
compensate-throw driver runs them (through their gate) in reverse order. All deterministic, no network.
"""
from __future__ import annotations

from typing import Any, Dict

_ARTIFACT = "art.pay.val"


def _uetr(envelope: Dict[str, Any]) -> str:
    return (envelope.get("payment") or {}).get("uetr", "UETR-?")


def release(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    uetr = _uetr(envelope)
    if mode == "propose":
        return {"proposed_actions": [{"action_id": "act-release", "kind": "release_payment",
                                      "summary": f"Release payment {uetr}", "detail": {"uetr": uetr}}],
                "log": "proposed release (no side effect)"}
    return {"outputs": {_ARTIFACT: {"ok": True, "ref": f"release:{uetr}"}}, "log": f"released {uetr}"}


def debit(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    uetr = _uetr(envelope)
    if mode == "propose":
        return {"proposed_actions": [{"action_id": "act-debit", "kind": "debit_account",
                                      "summary": f"Debit for {uetr}", "detail": {"uetr": uetr}}],
                "log": "proposed debit (no side effect)"}
    return {"outputs": {_ARTIFACT: {"ok": True, "ref": f"debit:{uetr}"}}, "log": f"debited {uetr}"}


def reverse_release(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    uetr = _uetr(envelope)
    if mode == "propose":
        return {"proposed_actions": [{"action_id": "act-reverse-release", "kind": "reverse_release",
                                      "summary": f"Reverse the release of {uetr}", "detail": {"uetr": uetr}}],
                "log": "proposed reverse-release (no side effect)"}
    return {"outputs": {}, "log": f"REVERSED release for {uetr}"}


def reverse_debit(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    uetr = _uetr(envelope)
    if mode == "propose":
        return {"proposed_actions": [{"action_id": "act-reverse-debit", "kind": "reverse_debit",
                                      "summary": f"Reverse the debit for {uetr}", "detail": {"uetr": uetr}}],
                "log": "proposed reverse-debit (no side effect)"}
    return {"outputs": {}, "log": f"REVERSED debit for {uetr}"}
