# app/engine/task_runner.py
"""The generic per-node task runner: gather inputs → (gate) → execute → validate →
(gate) → commit → log.

One factory (``make_task_node``) turns a bound BPMN element into a synchronous
LangGraph node. Nodes are pure w.r.t. IO: capabilities run through the injected
executor, schema validation uses pre-fetched pinned schemas, and human gates are
raised via LangGraph ``interrupt`` — the async engine materializes the HitlTask
from the interrupt payload and resumes the node with the decision.

Because LangGraph re-executes the interrupted node from the top on each resume,
capabilities must be deterministic (they are, in simulation): re-running propose
mode has no side effects, and execute mode only runs on the final (post-approval)
pass.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from jsonschema import Draft202012Validator
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from amendia_bpmn import parse_iso_duration
from amendia_contracts.capability import CapabilityDescriptor
from app.engine.executor import (
    CancellationToken,
    CapabilityBusinessError,
    CapabilityError,
    ExecutionContext,
    Executor,
)
from app.engine.state import actor_entry, now_iso

logger = logging.getLogger(__name__)

# ADR-040: how often (real seconds) the deadline loop re-reads the injected clock while waiting on a
# running capability. Small enough to be responsive, large enough not to busy-spin.
_DEADLINE_POLL_SECONDS = 0.02


class NodeExecutionError(Exception):
    """A node failed terminally — the engine marks the instance ``failed``.

    ``reason`` is a short machine tag (e.g. ``schema_invalid``, ``actions_rejected``).
    """

    def __init__(self, message: str, reason: str = "node_error") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class IOSpec:
    name: str
    schema_ref: str  # pinned "art.key@x.y.z"


@dataclass
class OutputSpec:
    name: str
    artifact_key: str
    schema_ref: str  # pinned "art.key@x.y.z"
    json_schema: Dict[str, Any]


@dataclass
class NodeContext:
    element_id: str
    element_kind: str  # serviceTask | userTask
    hitl_mode: str     # none | review_after | approve_result | approve_actions | manual
    role: Optional[str]
    executor_type: str  # capability | human
    descriptor: Optional[CapabilityDescriptor] = None
    assist_descriptor: Optional[CapabilityDescriptor] = None
    inputs: List[IOSpec] = field(default_factory=list)
    outputs: List[OutputSpec] = field(default_factory=list)
    title: str = ""
    # ADR-031 (Phase 2.4): the business message a message catch / receive element awaits (message
    # executor only). Correlation anchor is the instance's exception_id/correlation_id + this name.
    message_name: Optional[str] = None
    # ADR-035: the error boundary codes attached to this element (its wired errorRefs, catch-all
    # dropped). Threaded into the executor (extras["error_codes"]) so a real llm/mcp/deep_agent path
    # can emit/label a legal modeled business error. Empty when the element has no error boundary.
    error_codes: List[str] = field(default_factory=list)
    # ADR-043 (Item G): set on a COMPENSABLE primary — the id of its compensation handler activity + the
    # enclosing scope. When such a node commits its side effect, ``_commit`` appends a compensation-log
    # entry (so a later compensate throw can reverse it). ``None`` on a non-compensable node.
    compensate_handler_id: Optional[str] = None
    compensate_scope: Optional[str] = None


def make_task_node(ctx: NodeContext, executor: Executor, *, simulation: bool,
                   boundary_timer: Optional[Any] = None,
                   clock: Optional[Callable[[], float]] = None,
                   scope_timers: Optional[List[Any]] = None) -> Callable:
    # ``config`` is injected by LangGraph; its thread id is the process_instance_id, which
    # the executor uses to scope per-instance memoization (ADR-019). Purely additive — with
    # memoization off (native default) it is unused.
    # ADR-040: ``boundary_timer`` (set only for a capability serviceTask host with an interrupting
    # timer boundary) arms an in-process SLA deadline on this node's own execution, measured by the
    # injected ``clock``. ADR-041: ``scope_timers`` is a list of ``(scope_id, duration_seconds)`` for
    # each enclosing subProcess timer boundary — the node also runs under the remaining scope budget
    # (read from ``state.scope_deadlines``). ``None``/empty → the ordinary path (byte-unchanged).
    _clock = clock or time.monotonic

    def node(state: Dict[str, Any], config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
        pid = ((config or {}).get("configurable") or {}).get("thread_id")
        try:
            return _run_node(ctx, executor, simulation, state, pid,
                             boundary_timer=boundary_timer, clock=_clock, scope_timers=scope_timers)
        except CapabilityBusinessError as exc:
            # ADR-030 (Phase 2.3): a MODELED business error. Mark the error boundary so the post-node
            # conditional edge routes to the matching (or catch-all) boundary target; the instance
            # stays running. An unmodeled code (no matching/catch-all boundary) falls through to
            # FAILURE_SINK — last_error carries the code. Record the capability + code in the log.
            return {
                "boundary": {ctx.element_id: {"kind": "error", "code": exc.error_code}},
                "last_error": f"business error: {exc.error_code}",
                "actor_log": [actor_entry(
                    ctx.element_id, _cap_id(ctx), "capability",
                    meta={"business_error": exc.error_code, **(exc.detail or {})},
                )],
            }
    node.__name__ = f"node_{ctx.element_id}"
    return node


# --------------------------------------------------------------------------- #
def _run_node(ctx: NodeContext, executor: Executor, simulation: bool, state: Dict[str, Any],
              pid: Optional[str] = None, *, boundary_timer: Optional[Any] = None,
              clock: Optional[Callable[[], float]] = None,
              scope_timers: Optional[List[Any]] = None) -> Dict[str, Any]:
    envelope = state["envelope"]
    inputs = _gather_inputs(ctx, state)

    if ctx.executor_type == "human":
        return _run_manual(ctx, executor, simulation, envelope, inputs, state, pid)

    # capability executor
    if ctx.hitl_mode == "approve_actions":
        return _run_approve_actions(ctx, executor, simulation, envelope, inputs, pid)
    if ctx.hitl_mode in ("review_after", "approve_result"):
        return _run_reviewed(ctx, executor, simulation, envelope, inputs, pid)
    # mode none — fully autonomous. A deep_agent must never run un-gated (ADR-021 Part D;
    # belt-and-suspenders with the registry check) — fail closed.
    if _is_deep_agent(ctx):
        raise NodeExecutionError(
            f"{ctx.element_id}: deep_agent capability must be behind a HITL gate, not 'none'",
            reason="deep_agent_ungated",
        )
    # ADR-040/041: an interrupting timer boundary on this running serviceTask (own) and/or the remaining
    # budget of every enclosing subProcess timer scope → self-enforce the EARLIEST deadline. On breach:
    # commit nothing, mark the boundary channel (own → element_id; scope → scope_id), route to the target.
    _clock = clock or time.monotonic
    deadlines: List[tuple] = []   # (absolute_deadline, breach_key, nominal_seconds)
    if boundary_timer is not None:
        dur = parse_iso_duration(boundary_timer.timer.value).total_seconds()
        deadlines.append((_clock() + dur, ctx.element_id, dur))
    for scope_id, scope_seconds in (scope_timers or []):
        sd = (state.get("scope_deadlines") or {}).get(scope_id)
        if sd is not None:
            deadlines.append((sd, scope_id, scope_seconds))
    if deadlines:
        return _run_autonomous_with_deadline(ctx, executor, simulation, envelope, inputs, pid,
                                             deadlines, _clock)
    committed, meta = _produce_outputs(ctx, executor, simulation, envelope, inputs, mode="execute", pid=pid)
    return _commit(ctx, committed, actor=_cap_id(ctx), kind="capability", cap_meta=meta)


def _run_autonomous_with_deadline(ctx, executor, simulation, envelope, inputs, pid,
                                  deadlines, clock) -> Dict[str, Any]:
    """ADR-040/041: run the autonomous capability under the EARLIEST of the supplied deadlines
    (``[(absolute, breach_key, seconds)]`` — a node's own timer boundary and/or its enclosing scope
    budgets), measured by the injected ``clock``. Runs execute+validate (the retry loop shares the one
    budget) in a worker; on breach, ``set()`` the cancellation token, **discard** the result
    (all-or-nothing — no partial artifact), and write only ``boundary[breach_key] = {"kind":"timer"}``
    (``breach_key`` = the node for its own boundary, the subProcess id for a scope) so the existing
    router routes to the boundary handler. The abandoned thread is cooperative — a well-behaved
    capability sees ``token.cancelled`` and returns early."""
    deadline, breach_key, seconds = min(deadlines, key=lambda d: d[0])
    token = CancellationToken(deadline_seconds=seconds)
    is_scope = breach_key != ctx.element_id
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"sla-{ctx.element_id}")
    try:
        future = pool.submit(_produce_outputs, ctx, executor, simulation, envelope, inputs,
                             mode="execute", pid=pid, token=token)
        while True:
            try:
                committed, meta = future.result(timeout=_DEADLINE_POLL_SECONDS)
                return _commit(ctx, committed, actor=_cap_id(ctx), kind="capability", cap_meta=meta)
            except FuturesTimeout:
                if clock() >= deadline:
                    token.set()  # cooperative: the capability may see this and return early
                    logger.warning("[%s] %s SLA timer boundary breached (~%.0fs) — cancelled, no commit",
                                   ctx.element_id, "scope" if is_scope else "node", seconds)
                    meta = {"scope": breach_key} if is_scope else {"sla_breach_seconds": seconds}
                    return {
                        "boundary": {breach_key: {"kind": "timer"}},
                        "actor_log": [actor_entry(breach_key, "timer", "timer", meta=meta)],
                    }
    finally:
        # Never block the graph on a runaway capability thread — its output is discarded either way.
        pool.shutdown(wait=False)


# --------------------------------------------------------------------------- #
def _gather_inputs(ctx: NodeContext, state: Dict[str, Any]) -> Dict[str, Any]:
    artifacts = state.get("artifacts", {})
    inputs: Dict[str, Any] = {}
    for spec in ctx.inputs:
        # Post-validation this must hold; assert loudly if the pack drifted.
        assert spec.name in artifacts, (
            f"missing required input '{spec.name}' for element '{ctx.element_id}' "
            f"(have: {sorted(artifacts)})"
        )
        inputs[spec.name] = artifacts[spec.name]
    return inputs


def _cap_id(ctx: NodeContext) -> str:
    return ctx.descriptor.capability_id if ctx.descriptor else ctx.element_id


def _is_deep_agent(ctx: NodeContext) -> bool:
    d = ctx.descriptor
    if d is None:
        return False
    k = d.kind
    return (k.value if hasattr(k, "value") else str(k)) == "deep_agent"


def _run_capability(ctx: NodeContext, descriptor, executor, simulation, envelope, inputs, *,
                    mode, approved=None, pid=None, attempt=0, token=None):
    exec_ctx = ExecutionContext(
        envelope=envelope, mode=mode, approved_action_ids=approved, simulation=simulation,
        cancel=token,  # ADR-040: cooperative cancellation token (None on the ordinary path)
        # Hand the declared output JSON Schemas to the executor so the real LLM path
        # can constrain generation to schema-valid artifacts (ignored in simulation).
        # ``element_id`` lets a sandbox tag its OTLP trace to the element (nemoclaw mode);
        # ``process_instance_id`` + ``memo_attempt`` scope per-instance memoization (ADR-019).
        extras={
            "output_schemas": {s.artifact_key: s.json_schema for s in ctx.outputs},
            "element_id": ctx.element_id,
            "process_instance_id": pid,
            "memo_attempt": attempt,
            # ADR-035: the element's legal error boundary codes for the real llm/mcp/deep_agent path.
            "error_codes": ctx.error_codes,
        },
    )
    return executor.execute(descriptor, inputs, exec_ctx)


def _validate(spec: OutputSpec, data: Any) -> Optional[str]:
    errors = sorted(Draft202012Validator(spec.json_schema).iter_errors(data), key=lambda e: e.path)
    if errors:
        e = errors[0]
        loc = "/".join(str(p) for p in e.path)
        return f"{spec.schema_ref} invalid at '{loc or '<root>'}': {e.message}"
    return None


def _produce_outputs(ctx, executor, simulation, envelope, inputs, *, mode, approved=None,
                     pid=None, memo_attempt=0, token=None):
    """Run execute + validate, retrying per the descriptor's idempotency policy.

    Returns ``({binding_output_name: data}, exec_meta_or_None)`` — ``exec_meta`` is the
    optional executor metadata (e.g. a sandbox OTLP trace id) recorded in the ``actor_log``
    entry; it is ``None`` in native mode. ``memo_attempt`` scopes the per-instance memo key
    so a reject → re-run genuinely re-invokes the capability while HITL replays hit the memo
    (ADR-019).
    """
    descriptor = ctx.descriptor
    idempotent = bool(getattr(descriptor, "idempotent", False))
    max_retries = 0
    if descriptor and descriptor.constraints:
        max_retries = descriptor.constraints.max_retries or 0

    exec_attempts = (max_retries if idempotent else 0) + 1
    last_err: Optional[str] = None
    validation_retry_used = False

    for attempt in range(exec_attempts):
        try:
            result = _run_capability(ctx, descriptor, executor, simulation, envelope, inputs,
                                     mode=mode, approved=approved, pid=pid, attempt=memo_attempt, token=token)
        except CapabilityError as exc:
            last_err = str(exc)
            logger.warning("execute error for %s (attempt %d/%d): %s",
                           ctx.element_id, attempt + 1, exec_attempts, exc)
            continue

        produced = result.get("outputs", {}) or {}
        committed, verr = _map_and_validate(ctx, produced)
        if verr is None:
            if result.get("log"):
                logger.info("[%s] %s", ctx.element_id, result["log"])
            return committed, result.get("exec_meta")
        # validation failed → retry once if idempotent, else fail
        last_err = verr
        if idempotent and not validation_retry_used:
            validation_retry_used = True
            logger.warning("output schema-invalid for %s; retrying once: %s", ctx.element_id, verr)
            try:
                result = _run_capability(ctx, descriptor, executor, simulation, envelope, inputs,
                                         mode=mode, approved=approved, pid=pid, attempt=memo_attempt, token=token)
            except CapabilityError as exc:
                raise NodeExecutionError(f"{ctx.element_id}: {exc}", reason="execution_error") from exc
            committed, verr2 = _map_and_validate(ctx, result.get("outputs", {}) or {})
            if verr2 is None:
                return committed, result.get("exec_meta")
            raise NodeExecutionError(f"{ctx.element_id}: {verr2}", reason="schema_invalid")
        raise NodeExecutionError(f"{ctx.element_id}: {verr}", reason="schema_invalid")

    raise NodeExecutionError(
        f"{ctx.element_id}: execution failed after {exec_attempts} attempt(s): {last_err}",
        reason="execution_error",
    )


def _map_and_validate(ctx: NodeContext, produced: Dict[str, Any]):
    """Map capability outputs (keyed by artifact_key) → binding names + validate."""
    committed: Dict[str, Any] = {}
    for spec in ctx.outputs:
        data = produced.get(spec.artifact_key)
        if data is None:
            return {}, f"{ctx.element_id}: no output for {spec.artifact_key}"
        err = _validate(spec, data)
        if err:
            return {}, err
        committed[spec.name] = data
    return committed, None


def _commit(ctx: NodeContext, committed: Dict[str, Any], *, actor: str, kind: str,
            extra_actors: Optional[List[Dict[str, Any]]] = None,
            cap_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    log = list(extra_actors or [])
    # ``cap_meta`` (executor metadata, e.g. a sandbox trace id) attaches to the primary
    # entry only when it is the capability itself; human-primary paths pass the capability's
    # meta on its own ``extra_actors`` entry.
    log.append(actor_entry(ctx.element_id, actor, kind, meta=cap_meta if kind == "capability" else None))
    delta: Dict[str, Any] = {"artifacts": committed, "actor_log": log}
    # ADR-043 (Item G): a compensable primary appends a compensation-log entry on commit — the snapshot
    # (its committed outputs) is what a later compensate throw hands the undo handler. Append-only, so a
    # re-run of this node (idempotent capability) simply re-appends an identical entry keyed by
    # activity_id; the throw driver de-dupes by activity via ``compensations_done``.
    if ctx.compensate_handler_id is not None:
        delta["compensation_log"] = [{
            "activity_id": ctx.element_id,
            "handler_id": ctx.compensate_handler_id,
            "scope": ctx.compensate_scope,
            "snapshot": committed,
            "at": now_iso(),
        }]
    return delta


# --------------------------------------------------------------------------- #
def _gate_artifacts(specs: List[IOSpec], data_by_name: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"name": s.name, "schema": s.schema_ref, "data": data_by_name.get(s.name)}
        for s in specs
        if s.name in data_by_name
    ]


def _gate_payload(ctx: NodeContext, *, artifacts: List[Dict[str, Any]],
                  proposed_actions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "element_id": ctx.element_id,
        "hitl_mode": ctx.hitl_mode,
        "role": ctx.role,
        "kind": "human" if ctx.executor_type == "human" else "capability",
        "title": ctx.title or ctx.element_id,
        "artifacts": artifacts,
    }
    if proposed_actions is not None:
        payload["proposed_actions"] = proposed_actions
    return payload


def _decision(resume: Any) -> Dict[str, Any]:
    if not isinstance(resume, dict) or "decision" not in resume:
        raise NodeExecutionError(f"invalid resume payload: {resume!r}", reason="bad_resume")
    return resume


def _is_timeout(resume: Any) -> bool:
    """True when the engine resumed this gate because its SLA timer boundary fired (Phase 2.2),
    rather than because a human decided."""
    return isinstance(resume, dict) and bool(resume.get("__timeout__"))


# --------------------------------------------------------------------------- #
def _run_reviewed(ctx, executor, simulation, envelope, inputs, pid=None) -> Dict[str, Any]:
    """review_after / approve_result: run, hold output, gate before commit."""
    committed, meta = _produce_outputs(ctx, executor, simulation, envelope, inputs, mode="execute", pid=pid)
    rejects = 0
    while True:
        resume = interrupt(_gate_payload(ctx, artifacts=_gate_artifacts_from_outputs(ctx, committed)))
        d = _decision(resume)
        decision = d["decision"]
        user = d.get("decided_by", "unknown")
        if decision in ("approve", "complete"):
            return _commit(ctx, committed, actor=user, kind="human",
                           extra_actors=[actor_entry(ctx.element_id, _cap_id(ctx), "capability", meta=meta)])
        if decision == "edit_and_approve":
            edited = _apply_edits(ctx, d.get("edits"))
            return _commit(ctx, edited, actor=user, kind="human",
                           extra_actors=[actor_entry(ctx.element_id, _cap_id(ctx), "capability", meta=meta)])
        if decision == "reject":
            rejects += 1
            if rejects >= 2:
                raise NodeExecutionError(
                    f"{ctx.element_id}: rejected twice — failing (v1 policy)",  # TODO escalate
                    reason="rejected",
                )
            # A genuine reject re-runs the capability under a fresh memo attempt, so replays
            # of this reject on later resumes hit the memo rather than re-invoking (ADR-019).
            committed, meta = _produce_outputs(ctx, executor, simulation, envelope, inputs,
                                               mode="execute", pid=pid, memo_attempt=rejects)
            continue
        raise NodeExecutionError(f"{ctx.element_id}: unexpected decision {decision!r}", reason="bad_decision")


def _gate_artifacts_from_outputs(ctx: NodeContext, committed: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"name": s.name, "schema": s.schema_ref, "data": committed.get(s.name)}
        for s in ctx.outputs
    ]


def _apply_edits(ctx: NodeContext, edits: Any) -> Dict[str, Any]:
    """edit_and_approve: replace output data with the human's edits, re-validate."""
    if not isinstance(edits, dict):
        raise NodeExecutionError(f"{ctx.element_id}: edits must be an object", reason="bad_edits")
    committed: Dict[str, Any] = {}
    for spec in ctx.outputs:
        # edits may be keyed by binding output name or artifact_key
        data = edits.get(spec.name, edits.get(spec.artifact_key))
        if data is None:
            raise NodeExecutionError(f"{ctx.element_id}: edits missing '{spec.name}'", reason="bad_edits")
        err = _validate(spec, data)
        if err:
            raise NodeExecutionError(f"{ctx.element_id}: edited {err}", reason="schema_invalid")
        committed[spec.name] = data
    return committed


def _run_approve_actions(ctx, executor, simulation, envelope, inputs, pid=None) -> Dict[str, Any]:
    """approve_actions: propose (no side effects) → gate → execute only on approval."""
    proposal = _run_capability(ctx, ctx.descriptor, executor, simulation, envelope, inputs,
                               mode="propose", pid=pid)
    actions = proposal.get("proposed_actions", []) or []
    resume = interrupt(_gate_payload(
        ctx, artifacts=_gate_artifacts(ctx.inputs, inputs), proposed_actions=actions,
    ))
    d = _decision(resume)
    decision = d["decision"]
    user = d.get("decided_by", "unknown")
    if decision == "reject":
        # No explicit rejection route from these tasks in the seed BPMN → fail the instance.
        raise NodeExecutionError(
            f"{ctx.element_id}: actions rejected — no rejection route in pack", reason="actions_rejected"
        )
    if decision != "approve":
        raise NodeExecutionError(f"{ctx.element_id}: unexpected decision {decision!r}", reason="bad_decision")
    approved_ids = d.get("approved_action_ids")  # None → all
    committed, meta = _produce_outputs(ctx, executor, simulation, envelope, inputs,
                                       mode="execute", approved=approved_ids, pid=pid)
    return _commit(ctx, committed, actor=user, kind="human",
                   extra_actors=[actor_entry(ctx.element_id, _cap_id(ctx), "capability", meta=meta)])


def _run_manual(ctx, executor, simulation, envelope, inputs, state, pid=None) -> Dict[str, Any]:
    """manual: human performs the task; assist_capability may pre-draft."""
    draft_by_name: Dict[str, Any] = {}
    extra_actors: List[Dict[str, Any]] = []
    if ctx.assist_descriptor is not None and ctx.outputs:
        assist = _run_capability(ctx, ctx.assist_descriptor, executor, simulation, envelope, inputs,
                                 mode="execute", pid=pid)
        produced = assist.get("outputs", {}) or {}
        for spec in ctx.outputs:
            if spec.artifact_key in produced:
                draft_by_name[spec.name] = produced[spec.artifact_key]
        extra_actors.append(actor_entry(
            ctx.element_id, ctx.assist_descriptor.capability_id, "capability",
            meta=assist.get("exec_meta"),
        ))

    gate_arts = _gate_artifacts(ctx.inputs, inputs)
    for name, data in draft_by_name.items():
        schema_ref = next((s.schema_ref for s in ctx.outputs if s.name == name), "")
        gate_arts.append({"name": name, "schema": schema_ref, "data": data, "draft": True})

    resume = interrupt(_gate_payload(ctx, artifacts=gate_arts))
    if _is_timeout(resume):
        # ADR-027 Phase 2.2: the interrupting SLA timer boundary fired while this gate was parked.
        # Do NOT commit any output; mark the timer boundary so the post-gate conditional edge routes
        # to the escalation target, and record the timer as the actor (not a human) in the audit log.
        return {"boundary": {ctx.element_id: {"kind": "timer"}},
                "actor_log": [actor_entry(ctx.element_id, "timer", "timer")]}
    d = _decision(resume)
    decision = d["decision"]
    user = d.get("decided_by", "unknown")
    if decision == "escalate":
        raise NodeExecutionError(f"{ctx.element_id}: escalated (no supervisor flow in v1)", reason="escalated")
    if decision != "complete":
        raise NodeExecutionError(f"{ctx.element_id}: unexpected decision {decision!r}", reason="bad_decision")

    # Commit the human's output (edits override the assist draft), if this task produces one.
    committed: Dict[str, Any] = {}
    if ctx.outputs:
        edits = d.get("edits")
        for spec in ctx.outputs:
            data = (edits or {}).get(spec.name) if isinstance(edits, dict) else None
            if data is None:
                data = draft_by_name.get(spec.name)
            if data is None:
                raise NodeExecutionError(
                    f"{ctx.element_id}: manual task has no data for '{spec.name}'", reason="missing_output"
                )
            err = _validate(spec, data)
            if err:
                raise NodeExecutionError(f"{ctx.element_id}: {err}", reason="schema_invalid")
            committed[spec.name] = data
    return _commit(ctx, committed, actor=user, kind="human", extra_actors=extra_actors)
