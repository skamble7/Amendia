# app/capabilities/composition.py
"""Tiny read-only skills for the cross-pack composition demo packs (ADR-039).

Each produces the shared ``art.compose.val`` (``{n, tag}``); a task increments ``n`` and appends to
``tag`` so a test can prove data flowed caller → callee (input_map) and back (output_map), scoped and
in order. Deterministic, envelope-free.
"""
from __future__ import annotations

from typing import Any, Dict

ARTIFACT_KEY = "art.compose.val"


def _in(inputs: Dict[str, Any]) -> Dict[str, Any]:
    v = next(iter((inputs or {}).values()), None)
    return v if isinstance(v, dict) else {"n": 0, "tag": ""}


def caller_seed(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    return {"outputs": {ARTIFACT_KEY: {"n": 10, "tag": "caller"}}, "log": "caller seed"}


def mid_bump(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    v = _in(inputs)
    return {"outputs": {ARTIFACT_KEY: {"n": v["n"] + 2, "tag": v["tag"] + "/mid"}}, "log": "mid"}


def top_seed(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    return {"outputs": {ARTIFACT_KEY: {"n": 1, "tag": "top"}}, "log": "top seed"}


def leaf(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    v = _in(inputs)
    return {"outputs": {ARTIFACT_KEY: {"n": v["n"] + 1, "tag": v["tag"] + "/leaf"}}, "log": "leaf"}


def caller_finish(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    v = _in(inputs)
    return {"outputs": {ARTIFACT_KEY: {"n": v["n"] + 100, "tag": v["tag"] + "/final"}}, "log": "finish"}


# ADR-041 scope-SLA demo: three independent autonomous read_only steps (each []→ its own artifact),
# so a subProcess of them can be interrupted by a scope-wide timer boundary.
def scope_a(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    return {"outputs": {ARTIFACT_KEY: {"n": 1, "tag": "a"}}, "log": "scope a"}


def scope_b(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    return {"outputs": {ARTIFACT_KEY: {"n": 2, "tag": "b"}}, "log": "scope b"}


def scope_c(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    return {"outputs": {ARTIFACT_KEY: {"n": 3, "tag": "c"}}, "log": "scope c"}


# ADR-042 event-handler demo: a main autonomous read_only screening step + a handler step the event
# sub-process runs when the scope is cancelled (error raised anywhere / scope SLA breached).
def event_screen(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    return {"outputs": {ARTIFACT_KEY: {"n": 7, "tag": "scr"}}, "log": "screen"}


def event_handle(*, inputs, envelope, mode="execute", approved_action_ids=None) -> Dict[str, Any]:
    return {"outputs": {ARTIFACT_KEY: {"n": 9, "tag": "hnd"}}, "log": "handle"}
