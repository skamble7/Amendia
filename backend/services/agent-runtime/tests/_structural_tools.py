# tests/_structural_tools.py
"""ADR-047 D2 — the structural demo-pack skills, moved to the FIXTURE layer.

The compose-*/scope/event/payment seed packs are structural test fixtures (they exercise call-activity,
subprocess-scope, event-subprocess and compensation *wiring*, not business logic). Their tiny skills used to
live in the platform image (`app/capabilities/composition.py`, `payment_comp.py`). Here they are **copied
verbatim** (not imported), keyed by capability_id, so a test can run the packs via
``InProcessExecutor(skill_impls=STRUCTURAL_IMPLS)`` — the skill behavior in the fixture, the platform image
carrying none of it (and this fixture survives the Stage-B deletion of the in-code modules).
"""
from __future__ import annotations

from typing import Any, Dict

_COMPOSE = "art.compose.val"
_PAY = "art.pay.val"


def _in(inputs: Dict[str, Any]) -> Dict[str, Any]:
    v = next(iter((inputs or {}).values()), None)
    return v if isinstance(v, dict) else {"n": 0, "tag": ""}


# --- composition (ADR-039 call-activity / ADR-041 scope / ADR-042 event) ------------------------------
def _caller_seed(**_):
    return {"outputs": {_COMPOSE: {"n": 10, "tag": "caller"}}, "log": "caller seed"}


def _mid_bump(*, inputs, **_):
    v = _in(inputs)
    return {"outputs": {_COMPOSE: {"n": v["n"] + 2, "tag": v["tag"] + "/mid"}}, "log": "mid"}


def _top_seed(**_):
    return {"outputs": {_COMPOSE: {"n": 1, "tag": "top"}}, "log": "top seed"}


def _leaf(*, inputs, **_):
    v = _in(inputs)
    return {"outputs": {_COMPOSE: {"n": v["n"] + 1, "tag": v["tag"] + "/leaf"}}, "log": "leaf"}


def _caller_finish(*, inputs, **_):
    v = _in(inputs)
    return {"outputs": {_COMPOSE: {"n": v["n"] + 100, "tag": v["tag"] + "/final"}}, "log": "finish"}


def _scope_a(**_): return {"outputs": {_COMPOSE: {"n": 1, "tag": "a"}}, "log": "scope a"}
def _scope_b(**_): return {"outputs": {_COMPOSE: {"n": 2, "tag": "b"}}, "log": "scope b"}
def _scope_c(**_): return {"outputs": {_COMPOSE: {"n": 3, "tag": "c"}}, "log": "scope c"}
def _event_screen(**_): return {"outputs": {_COMPOSE: {"n": 7, "tag": "scr"}}, "log": "screen"}
def _event_handle(**_): return {"outputs": {_COMPOSE: {"n": 9, "tag": "hnd"}}, "log": "handle"}


# --- payment compensation (ADR-043) — propose (proposed_actions) / execute (side effect) --------------
def _uetr(envelope: Dict[str, Any]) -> str:
    return (envelope.get("payment") or {}).get("uetr", "UETR-?")


def _release(*, envelope, mode="execute", **_):
    uetr = _uetr(envelope)
    if mode == "propose":
        return {"proposed_actions": [{"action_id": "act-release", "kind": "release_payment",
                                      "summary": f"Release payment {uetr}", "detail": {"uetr": uetr}}],
                "log": "proposed release (no side effect)"}
    return {"outputs": {_PAY: {"ok": True, "ref": f"release:{uetr}"}}, "log": f"released {uetr}"}


def _debit(*, envelope, mode="execute", **_):
    uetr = _uetr(envelope)
    if mode == "propose":
        return {"proposed_actions": [{"action_id": "act-debit", "kind": "debit_account",
                                      "summary": f"Debit for {uetr}", "detail": {"uetr": uetr}}],
                "log": "proposed debit (no side effect)"}
    return {"outputs": {_PAY: {"ok": True, "ref": f"debit:{uetr}"}}, "log": f"debited {uetr}"}


def _reverse_release(*, envelope, mode="execute", **_):
    uetr = _uetr(envelope)
    if mode == "propose":
        return {"proposed_actions": [{"action_id": "act-reverse-release", "kind": "reverse_release",
                                      "summary": f"Reverse the release of {uetr}", "detail": {"uetr": uetr}}],
                "log": "proposed reverse-release (no side effect)"}
    return {"outputs": {}, "log": f"REVERSED release for {uetr}"}


def _reverse_debit(*, envelope, mode="execute", **_):
    uetr = _uetr(envelope)
    if mode == "propose":
        return {"proposed_actions": [{"action_id": "act-reverse-debit", "kind": "reverse_debit",
                                      "summary": f"Reverse the debit for {uetr}", "detail": {"uetr": uetr}}],
                "log": "proposed reverse-debit (no side effect)"}
    return {"outputs": {}, "log": f"REVERSED debit for {uetr}"}


# capability_id → skill double (matches the wire seed packs' descriptor ids).
STRUCTURAL_IMPLS: Dict[str, Any] = {
    "cap.compose.seed": _caller_seed, "cap.compose.mid": _mid_bump, "cap.compose.top": _top_seed,
    "cap.compose.leaf": _leaf, "cap.compose.finish": _caller_finish,
    "cap.scope.sa": _scope_a, "cap.scope.sb": _scope_b, "cap.scope.sc": _scope_c,
    "cap.event.screen": _event_screen, "cap.event.handle": _event_handle,
    "cap.pay.release": _release, "cap.pay.debit": _debit,
    "cap.pay.reverse_release": _reverse_release, "cap.pay.reverse_debit": _reverse_debit,
}
