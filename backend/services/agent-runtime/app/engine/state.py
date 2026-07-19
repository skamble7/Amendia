# app/engine/state.py
"""The process execution state (LangGraph channels) + reducers.

Everything here is JSON-serializable so the Mongo checkpointer can persist it at
every node boundary — that checkpoint trail is the audit record.
"""
from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional, TypedDict


def merge_dicts(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Reducer for ``artifacts``: later node deltas overlay earlier ones."""
    out = dict(a or {})
    out.update(b or {})
    return out


class ProcessState(TypedDict, total=False):
    envelope: Dict[str, Any]
    artifacts: Annotated[Dict[str, Any], merge_dicts]
    actor_log: Annotated[List[Dict[str, Any]], operator.add]
    trace: Dict[str, Any]
    pack: Dict[str, Any]
    outcome: Optional[str]
    last_error: Optional[str]
    # ADR-027 Phase 2.2/2.3: element_id -> the boundary event a node was left through, if any. The
    # post-node conditional edge reads it to route to the boundary target instead of the normal flow:
    #   {"kind": "timer"}                     — an interrupting SLA timer boundary fired (Phase 2.2.d)
    #   {"kind": "error", "code": "<CODE>"}   — the capability signalled a modeled business error (2.3)
    # dict-merge so concurrent branches don't clobber each other's boundary marks.
    boundary: Annotated[Dict[str, Dict[str, Any]], merge_dicts]
    # ADR-031 Phase 2.4: element_id -> the untyped payload of a delivered message, when the message
    # binding declares no output artifact (a pure signal). Typed messages commit into `artifacts`.
    messages: Annotated[Dict[str, Any], merge_dicts]
    # ADR-036 (Backlog #3): multi-instance scratch — "{host}/{index}" -> that iteration's produced
    # outputs (keyed by artifact_key). N iterations write index-scoped keys so parallel writes NEVER
    # collide (the merge is by unique key, not last-wins on the bare binding); the MI join reads them
    # in index order and writes the aggregated final artifact into `artifacts`. Never read downstream.
    mi_results: Annotated[Dict[str, Any], merge_dicts]
    # ADR-041: subProcess-scope SLA deadlines — subprocess_id -> the absolute (injected-clock) deadline
    # stamped at scope entry. Every inner node runs under min(own, remaining-scope) and, on scope breach,
    # marks boundary[scope_id]={"kind":"timer"} to divert the whole scope to its timer-boundary handler.
    scope_deadlines: Annotated[Dict[str, float], merge_dicts]
    # ADR-043 (Backlog #4, Item G): compensation. ``compensation_log`` is an APPEND-only list — each
    # compensable side-effectful activity, on successful commit, appends
    # {activity_id, handler_id, scope, snapshot, at}; completion order = list order, so LIFO = reversed.
    # ``compensations_done`` is a companion merge-dict (activity_id -> True) the compensate-throw driver
    # sets as each handler's undo commits — so a re-run-from-top (HITL-resume replay or crash recovery)
    # NEVER compensates the same activity twice (the append-only log can't be mutated in place).
    compensation_log: Annotated[List[Dict[str, Any]], operator.add]
    compensations_done: Annotated[Dict[str, bool], merge_dicts]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def actor_entry(element_id: str, actor: str, kind: str,
                meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One ``actor_log`` entry — kind is ``capability`` or ``human``.

    ``meta`` is optional executor metadata (e.g. an OpenShell OTLP ``exec_meta`` in
    nemoclaw mode). It is omitted entirely when absent, so native-mode entries are
    byte-for-byte unchanged (ADR-017 §8.1).
    """
    entry: Dict[str, Any] = {"element_id": element_id, "actor": actor, "kind": kind, "at": now_iso()}
    if meta:
        entry["exec_meta"] = meta
    return entry


def initial_state(*, envelope: Dict[str, Any], trace: Dict[str, Any], pack: Dict[str, Any]) -> ProcessState:
    return {
        "envelope": envelope,
        "artifacts": {},
        "actor_log": [],
        "trace": trace,
        "pack": pack,
        "outcome": None,
        "last_error": None,
        "boundary": {},
        "messages": {},
        "mi_results": {},
        "scope_deadlines": {},
        "compensation_log": [],
        "compensations_done": {},
    }
