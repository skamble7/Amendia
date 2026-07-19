# app/engine/compensation.py
"""Compensation (ADR-043 / Backlog #4, Item G): reverse already-committed side effects when a later step
fails — "undo the partial repair we released."

A compensable side-effectful activity, on commit, appends a ``compensation_log`` entry
(``{activity_id, handler_id, scope, snapshot}``) via the task runner. A **compensate throw** event
(``compensateEventDefinition`` on an intermediate/end event) compiles to a **self-looping driver node**
that, each superstep, picks the most-recently-completed **not-yet-compensated** activity in its scope
(LIFO) and runs that activity's bound **undo handler** through the ordinary task-runner path — including
its HITL gate. It marks the activity in ``compensations_done`` as the undo commits, so a re-run from the
top (an HITL-resume replay, or crash recovery) **never compensates the same activity twice**: exactly one
undo per activity per superstep (LangGraph's single-interrupt-per-node guarantee), never re-processed
across supersteps (the persisted ``compensations_done`` flag). The conditional edge loops back to the
driver while any pending remain, then proceeds to the throw's continuation (an outgoing flow, or END for
a terminal end-event throw).

Scope-wide only this cut: a process-level throw compensates every compensable activity; a subProcess-scoped
throw compensates that scope's. Targeted (``activityRef``), transaction/cancel-triggered, and multi-instance
compensation are refused by the shared ``compilability`` gate.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from langchain_core.runnables import RunnableConfig

from app.engine.executor import Executor
from app.engine.task_runner import NodeContext, _run_node


def pending_compensations(state: Dict[str, Any], scope: str, process_id: str) -> List[Dict[str, Any]]:
    """The compensable activities in ``scope`` still to undo, most-recently-completed first (LIFO), one
    per activity id. A process-level throw (``scope == process_id``) covers every compensable activity."""
    log = state.get("compensation_log") or []
    done = state.get("compensations_done") or {}
    scope_wide = scope == process_id
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for entry in reversed(log):                       # reversed completion order = LIFO
        aid = entry.get("activity_id")
        if not (scope_wide or entry.get("scope") == scope):
            continue
        if aid in done or aid in seen:                # already undone, or a duplicate log entry
            continue
        seen.add(aid)
        out.append(entry)
    return out


def make_compensation_driver(throw_id: str, scope: str, process_id: str,
                             handler_ctxs: Dict[str, NodeContext], executor: Executor,
                             *, simulation: bool) -> Callable:
    """A compensate-throw driver: compensate ONE activity per superstep (LIFO), running its handler's undo
    through the ordinary task-runner path (HITL gate included), then mark it done. Re-entrant: on a
    resume-replay it re-selects the SAME pending entry (``compensations_done`` is unchanged until the node
    returns), so the undo executes exactly once; across supersteps the persisted flag skips it."""
    def node(state: Dict[str, Any], config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
        pid = ((config or {}).get("configurable") or {}).get("thread_id")
        pending = pending_compensations(state, scope, process_id)
        if not pending:
            return {}
        entry = pending[0]
        activity_id = entry["activity_id"]
        hctx = handler_ctxs.get(entry.get("handler_id"))
        if hctx is None:                              # fail-closed: no handler (should not pass validation)
            return {"compensations_done": {activity_id: True}}
        # Run the undo handler (may interrupt for its HITL gate). One handler per superstep → one
        # interrupt max, so the execute (side effect) runs exactly once on the final resume pass.
        delta = dict(_run_node(hctx, executor, simulation, state, pid))
        done = dict(delta.get("compensations_done") or {})
        done[activity_id] = True
        delta["compensations_done"] = done
        return delta
    node.__name__ = f"comp_{throw_id}"
    return node


def make_compensation_router(throw_id: str, scope: str, process_id: str, done_target: str) -> Callable:
    """Loop back to the driver while any compensation is pending in scope; else proceed to ``done_target``
    (the throw's outgoing successor, or a terminal end node for an end-event throw)."""
    def router(state: Dict[str, Any]) -> str:
        return throw_id if pending_compensations(state, scope, process_id) else done_target
    return router
