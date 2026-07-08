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
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from jsonschema import Draft202012Validator
from langgraph.types import interrupt

from amendia_contracts.capability import CapabilityDescriptor
from app.engine.executor import CapabilityError, ExecutionContext, Executor
from app.engine.state import actor_entry

logger = logging.getLogger(__name__)


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


def make_task_node(ctx: NodeContext, executor: Executor, *, simulation: bool) -> Callable:
    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        return _run_node(ctx, executor, simulation, state)
    node.__name__ = f"node_{ctx.element_id}"
    return node


# --------------------------------------------------------------------------- #
def _run_node(ctx: NodeContext, executor: Executor, simulation: bool, state: Dict[str, Any]) -> Dict[str, Any]:
    envelope = state["envelope"]
    inputs = _gather_inputs(ctx, state)

    if ctx.executor_type == "human":
        return _run_manual(ctx, executor, simulation, envelope, inputs, state)

    # capability executor
    if ctx.hitl_mode == "approve_actions":
        return _run_approve_actions(ctx, executor, simulation, envelope, inputs)
    if ctx.hitl_mode in ("review_after", "approve_result"):
        return _run_reviewed(ctx, executor, simulation, envelope, inputs)
    # mode none — fully autonomous
    committed = _produce_outputs(ctx, executor, simulation, envelope, inputs, mode="execute")
    return _commit(ctx, committed, actor=_cap_id(ctx), kind="capability")


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


def _run_capability(ctx: NodeContext, descriptor, executor, simulation, envelope, inputs, *, mode, approved=None):
    exec_ctx = ExecutionContext(
        envelope=envelope, mode=mode, approved_action_ids=approved, simulation=simulation
    )
    return executor.execute(descriptor, inputs, exec_ctx)


def _validate(spec: OutputSpec, data: Any) -> Optional[str]:
    errors = sorted(Draft202012Validator(spec.json_schema).iter_errors(data), key=lambda e: e.path)
    if errors:
        e = errors[0]
        loc = "/".join(str(p) for p in e.path)
        return f"{spec.schema_ref} invalid at '{loc or '<root>'}': {e.message}"
    return None


def _produce_outputs(ctx, executor, simulation, envelope, inputs, *, mode, approved=None) -> Dict[str, Any]:
    """Run execute + validate, retrying per the descriptor's idempotency policy.

    Returns ``{binding_output_name: data}`` (empty for zero-output tasks).
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
                                     mode=mode, approved=approved)
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
            return committed
        # validation failed → retry once if idempotent, else fail
        last_err = verr
        if idempotent and not validation_retry_used:
            validation_retry_used = True
            logger.warning("output schema-invalid for %s; retrying once: %s", ctx.element_id, verr)
            try:
                result = _run_capability(ctx, descriptor, executor, simulation, envelope, inputs,
                                         mode=mode, approved=approved)
            except CapabilityError as exc:
                raise NodeExecutionError(f"{ctx.element_id}: {exc}", reason="execution_error") from exc
            committed, verr2 = _map_and_validate(ctx, result.get("outputs", {}) or {})
            if verr2 is None:
                return committed
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
            extra_actors: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    log = list(extra_actors or [])
    log.append(actor_entry(ctx.element_id, actor, kind))
    return {"artifacts": committed, "actor_log": log}


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


# --------------------------------------------------------------------------- #
def _run_reviewed(ctx, executor, simulation, envelope, inputs) -> Dict[str, Any]:
    """review_after / approve_result: run, hold output, gate before commit."""
    committed = _produce_outputs(ctx, executor, simulation, envelope, inputs, mode="execute")
    rejects = 0
    while True:
        resume = interrupt(_gate_payload(ctx, artifacts=_gate_artifacts_from_outputs(ctx, committed)))
        d = _decision(resume)
        decision = d["decision"]
        user = d.get("decided_by", "unknown")
        if decision in ("approve", "complete"):
            return _commit(ctx, committed, actor=user, kind="human",
                           extra_actors=[actor_entry(ctx.element_id, _cap_id(ctx), "capability")])
        if decision == "edit_and_approve":
            edited = _apply_edits(ctx, d.get("edits"))
            return _commit(ctx, edited, actor=user, kind="human",
                           extra_actors=[actor_entry(ctx.element_id, _cap_id(ctx), "capability")])
        if decision == "reject":
            rejects += 1
            if rejects >= 2:
                raise NodeExecutionError(
                    f"{ctx.element_id}: rejected twice — failing (v1 policy)",  # TODO escalate
                    reason="rejected",
                )
            committed = _produce_outputs(ctx, executor, simulation, envelope, inputs, mode="execute")
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


def _run_approve_actions(ctx, executor, simulation, envelope, inputs) -> Dict[str, Any]:
    """approve_actions: propose (no side effects) → gate → execute only on approval."""
    proposal = _run_capability(ctx, ctx.descriptor, executor, simulation, envelope, inputs, mode="propose")
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
    committed = _produce_outputs(ctx, executor, simulation, envelope, inputs,
                                 mode="execute", approved=approved_ids)
    return _commit(ctx, committed, actor=user, kind="human",
                   extra_actors=[actor_entry(ctx.element_id, _cap_id(ctx), "capability")])


def _run_manual(ctx, executor, simulation, envelope, inputs, state) -> Dict[str, Any]:
    """manual: human performs the task; assist_capability may pre-draft."""
    draft_by_name: Dict[str, Any] = {}
    extra_actors: List[Dict[str, Any]] = []
    if ctx.assist_descriptor is not None and ctx.outputs:
        assist = _run_capability(ctx, ctx.assist_descriptor, executor, simulation, envelope, inputs, mode="execute")
        produced = assist.get("outputs", {}) or {}
        for spec in ctx.outputs:
            if spec.artifact_key in produced:
                draft_by_name[spec.name] = produced[spec.artifact_key]
        extra_actors.append(actor_entry(ctx.element_id, ctx.assist_descriptor.capability_id, "capability"))

    gate_arts = _gate_artifacts(ctx.inputs, inputs)
    for name, data in draft_by_name.items():
        schema_ref = next((s.schema_ref for s in ctx.outputs if s.name == name), "")
        gate_arts.append({"name": name, "schema": schema_ref, "data": data, "draft": True})

    resume = interrupt(_gate_payload(ctx, artifacts=gate_arts))
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
