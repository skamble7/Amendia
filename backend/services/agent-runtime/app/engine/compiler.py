# app/engine/compiler.py
"""Compile a PackBundle (BPMN + manifest + resolution) into a LangGraph StateGraph.

Deterministic: the same bundle always produces the same graph. Compilation is
Mongo-free and unit-testable; a checkpointer is attached at ``compile`` time so
interrupts persist and resume.

Mapping:
  * bound serviceTask/userTask → one node (the generic task runner).
  * startEvent                 → START edge to its successor.
  * endEvent                   → a marker node that records ``outcome`` → END.
  * sequenceFlow               → edge.
  * exclusiveGateway           → conditional edge (router over flow conditions),
                                 default flow, else the compiled-in failure sink.
  * parallelGateway            → CompilerError (unsupported in this slice).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

from langgraph.graph import END, START, StateGraph

from app.engine import expr
from app.engine.bundle import PackBundle, build_node_contexts
from app.engine.executor import Executor
from app.engine.state import ProcessState
from app.engine.task_runner import make_task_node

logger = logging.getLogger(__name__)

FAILURE_SINK = "__failure__"
FAILED_OUTCOME = "__failed__"


class CompilerError(Exception):
    """The pack cannot be compiled to a runnable graph."""


def compile_graph(bundle: PackBundle, executor: Executor, *, simulation: bool, checkpointer):
    model = bundle.bpmn_model
    if model.parallel_gateways:
        raise CompilerError(
            f"parallelGateway not supported in this slice: {model.parallel_gateways} "
            f"(pack {bundle.pack_key}@{bundle.pack_version})"
        )
    if len(model.start_events) != 1:
        raise CompilerError(f"expected exactly one startEvent, found {model.start_events}")

    node_ctxs = build_node_contexts(bundle)
    tasks = set(model.tasks)
    ends = set(model.end_events)
    gateways = set(model.exclusive_gateways)

    # every task must be bound
    missing = tasks - set(node_ctxs)
    if missing:
        raise CompilerError(f"unbound BPMN tasks (no manifest binding): {sorted(missing)}")

    g = StateGraph(ProcessState)

    for element_id, ctx in node_ctxs.items():
        g.add_node(element_id, make_task_node(ctx, executor, simulation=simulation))

    for end_id in model.end_events:
        g.add_node(end_id, _make_end_node(end_id))
        g.add_edge(end_id, END)

    g.add_node(FAILURE_SINK, _failure_node)
    g.add_edge(FAILURE_SINK, END)

    def resolve_node(target: str) -> str:
        if target in tasks or target in ends:
            return target
        if target in gateways:
            raise CompilerError(f"chained gateways not supported (target '{target}' is a gateway)")
        raise CompilerError(f"flow targets unknown/unsupported node '{target}'")

    # START → the start event's single successor
    start_out = model.outgoing(model.start_events[0])
    if len(start_out) != 1:
        raise CompilerError(f"startEvent must have exactly one outgoing flow, has {len(start_out)}")
    g.add_edge(START, resolve_node(start_out[0].target))

    # task edges (single outgoing per task in this subset) — direct edge or gateway router
    for element_id in node_ctxs:
        outs = model.outgoing(element_id)
        if len(outs) != 1:
            raise CompilerError(
                f"task '{element_id}' must have exactly one outgoing flow, has {len(outs)}"
            )
        target = outs[0].target
        if target in gateways:
            router, path_map = _build_gateway_router(bundle, model, target, resolve_node)
            g.add_conditional_edges(element_id, router, path_map)
        else:
            g.add_edge(element_id, resolve_node(target))

    return g.compile(checkpointer=checkpointer)


def _make_end_node(end_id: str) -> Callable:
    def end_node(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"outcome": end_id}
    end_node.__name__ = f"end_{end_id}"
    return end_node


def _failure_node(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "outcome": FAILED_OUTCOME,
        "last_error": state.get("last_error") or "no gateway route matched and no default flow",
    }


def _build_gateway_router(bundle, model, gateway_id, resolve_node):
    """Router closure evaluating a gateway's flow conditions against artifacts."""
    flows = model.outgoing(gateway_id)
    default_flow_id = model.gateway_defaults.get(gateway_id)
    conditional: List[tuple] = []   # (expr, target_node)
    default_target = None
    targets: set[str] = set()

    for fl in flows:
        target_node = resolve_node(fl.target)
        targets.add(target_node)
        if fl.id == default_flow_id:
            default_target = target_node
            continue
        if not fl.condition_expr:
            # A conditionless non-default flow is a malformed gateway (registry blocks this).
            raise CompilerError(
                f"gateway '{gateway_id}' flow '{fl.id}' has no condition and is not the default"
            )
        try:
            expr.parse_condition(fl.condition_expr)  # validate at compile time
        except expr.ConditionSyntaxError as exc:
            raise CompilerError(f"gateway '{gateway_id}': {exc}") from exc
        conditional.append((fl.condition_expr, target_node))

    def router(state: Dict[str, Any]) -> str:
        artifacts = state.get("artifacts", {})
        for condition, target in conditional:
            try:
                if expr.evaluate(condition, artifacts):
                    return target
            except expr.ConditionSyntaxError:  # pragma: no cover - validated at compile
                return FAILURE_SINK
        if default_target is not None:
            return default_target
        return FAILURE_SINK

    path_map = {t: t for t in targets}
    path_map[FAILURE_SINK] = FAILURE_SINK
    return router, path_map
