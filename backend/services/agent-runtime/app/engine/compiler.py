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
  * parallelGateway            → under the ``parallel`` execution profile (ADR-027 Phase 2.1),
                                 a passthrough node: a fork fans out to its N successors (they run
                                 in one superstep; ``artifacts``/``actor_log`` reducers merge the
                                 concurrent writes), a join is a barrier (LangGraph runs it once all
                                 N incoming branches complete). Under ``common_subset`` it is
                                 refused before we get here (``compilability_findings``).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from amendia_bpmn import compilability_findings
from app.engine import expr
from app.engine.bundle import PackBundle, build_node_contexts
from app.engine.executor import Executor
from app.engine.state import ProcessState, actor_entry
from app.engine.task_runner import make_task_node

logger = logging.getLogger(__name__)

FAILURE_SINK = "__failure__"
FAILED_OUTCOME = "__failed__"


class CompilerError(Exception):
    """The pack cannot be compiled to a runnable graph."""


def compile_graph(bundle: PackBundle, executor: Executor, *, simulation: bool, checkpointer,
                  profile: str = "common_subset"):
    model = bundle.bpmn_model
    # ADR-027 §1a / Phase 2: refuse the un-runnable structural constructs off the SAME shared
    # predicate the registry gates activation with — so runtime and registry can never diverge on
    # "what activates but won't run". `profile` decides whether parallel gateways are runnable.
    blockers = compilability_findings(model, profile=profile)
    if blockers:
        raise CompilerError(
            f"{blockers[0].message} (pack {bundle.pack_key}@{bundle.pack_version})"
        )
    if len(model.start_events) != 1:
        raise CompilerError(f"expected exactly one startEvent, found {model.start_events}")

    node_ctxs = build_node_contexts(bundle)
    tasks = set(model.tasks)
    ends = set(model.end_events)
    gateways = set(model.exclusive_gateways)       # exclusive → conditional router
    parallels = set(model.parallel_gateways)       # parallel  → fork/join passthrough (parallel profile)
    event_gateways = model.event_based_gateways    # {gw: [arm catch ids]} (messages profile)
    # ADR-031: an event gateway's arm catch events are handled BY the gateway, not as standalone
    # parking nodes — exclude them from the standalone message/timer catch node sets.
    arm_ids = {a for arms in event_gateways.values() for a in arms}
    timer_catches = set(model.timer_catch_events) - arm_ids   # standalone timer intermediate-catch
    message_catches = set(model.message_catch_events) - arm_ids  # standalone message catch (Phase 2.4)
    receive_tasks = set(model.receive_tasks) - arm_ids           # receive task (Phase 2.4)
    message_nodes = message_catches | receive_tasks              # both park WAITING_MESSAGE

    # every task must be bound (message catch/receive are also in node_ctxs — bound via message binding)
    missing = tasks - set(node_ctxs)
    if missing:
        raise CompilerError(f"unbound BPMN tasks (no manifest binding): {sorted(missing)}")

    g = StateGraph(ProcessState)

    for element_id, ctx in node_ctxs.items():
        if element_id in message_nodes or element_id in arm_ids:
            continue  # message catch/receive → message node; event-gateway arms → handled by gateway
        g.add_node(element_id, make_task_node(ctx, executor, simulation=simulation))

    for end_id in model.end_events:
        g.add_node(end_id, _make_end_node(end_id))
        g.add_edge(end_id, END)

    # Parallel gateways compile to passthrough nodes: a fork's N outgoing edges fan out (parallel
    # superstep); a join's N incoming edges make LangGraph wait for all branches (barrier).
    for gw in parallels:
        g.add_node(gw, _passthrough_node(gw))

    # Timer intermediate-catch events (Phase 2.2): a node that interrupts on entry so the engine
    # parks WAITING_TIMER, then auto-proceeds when the poller resumes it at the timer's fire_at.
    for cid in timer_catches:
        g.add_node(cid, _timer_catch_node(cid))

    # Message catch / receive nodes (Phase 2.4): interrupt on entry so the engine registers a
    # subscription and parks WAITING_MESSAGE; resume on correlated delivery.
    for mid in message_nodes:
        sub_kind = "receive" if mid in receive_tasks else "catch"
        g.add_node(mid, _message_node(node_ctxs[mid], sub_kind))

    # Event-based gateways (Phase 2.4 capstone): interrupt on entry so the engine registers ALL arms
    # (timer + message) and parks; first arm to fire wins, the losers are cancelled.
    for gw in event_gateways:
        g.add_node(gw, _event_gateway_node(gw))

    g.add_node(FAILURE_SINK, _failure_node)
    g.add_edge(FAILURE_SINK, END)

    # ADR-032 Phase 2.6: inline embedded sub-processes. A flow targeting a subProcess box routes to
    # its start's successor; a flow targeting an internal (nested) end routes to the box's parent-level
    # outgoing target. Both recurse (nested sub-processes), so the whole scope is flattened into one
    # graph and the sub-process start/end become edges, not nodes.
    end_to_sub = {eid: sub for sub in model.subprocesses.values() for eid in sub.end_ids}

    def resolve_node(target: str) -> str:
        if target in model.subprocesses:
            sub = model.subprocesses[target]
            outs = model.outgoing(sub.start_id) if sub.start_id else []
            if len(outs) != 1:
                raise CompilerError(f"sub-process '{target}' start must have exactly one outgoing flow")
            return resolve_node(outs[0].target)
        if target in end_to_sub:
            sub = end_to_sub[target]
            outs = model.outgoing(sub.id)
            if len(outs) != 1:
                raise CompilerError(f"sub-process '{sub.id}' must have exactly one parent outgoing flow")
            return resolve_node(outs[0].target)
        if (target in tasks or target in ends or target in parallels or target in timer_catches
                or target in message_nodes or target in event_gateways):
            return target
        if target in gateways:
            raise CompilerError(f"chained gateways not supported (target '{target}' is a gateway)")
        raise CompilerError(f"flow targets unknown/unsupported node '{target}'")

    def single_out_edge(source_id: str) -> None:
        """Wire a single-outgoing node (task or timer-catch): direct edge, or an exclusive-gateway
        router, with boundary-event exits layered on top. Boundaries are read from the unified
        ``state.boundary[source]`` channel: an interrupting timer boundary (Phase 2.2.d) OR error
        boundaries (Phase 2.3) that route a modeled business error by code (else a catch-all, else
        FAILURE_SINK). The node keeps its single normal outgoing flow; boundaries are the extra exits."""
        outs = model.outgoing(source_id)
        if len(outs) != 1:
            raise CompilerError(f"node '{source_id}' must have exactly one outgoing flow, has {len(outs)}")
        target = outs[0].target
        timer_boundary = model.boundary_timers.get(source_id)
        error_boundaries = model.error_boundaries.get(source_id, [])
        is_gateway = target in gateways

        if timer_boundary is None and not error_boundaries:
            # No boundary: a plain edge, or an exclusive-gateway router.
            if is_gateway:
                router, path_map = _build_gateway_router(bundle, model, target, resolve_node)
                g.add_conditional_edges(source_id, router, path_map)
            else:
                g.add_edge(source_id, resolve_node(target))
            return

        # Base (normal) routing — the node's single outgoing flow.
        if is_gateway:
            base_router, base_map = _build_gateway_router(bundle, model, target, resolve_node)
        else:
            resolved = resolve_node(target)
            base_router, base_map = (lambda _s, _r=resolved: _r), {resolved: resolved}
        path_map: Dict[str, str] = dict(base_map)

        timer_target = None
        if timer_boundary is not None:
            timer_target = resolve_node(timer_boundary.target)
            path_map[timer_target] = timer_target

        error_by_code: Dict[str, str] = {}
        catch_all_target = None
        for eb in error_boundaries:
            t = resolve_node(eb.target)
            path_map[t] = t
            if eb.error_code is None:
                catch_all_target = t
            else:
                error_by_code[eb.error_code] = t
        # An unmodeled business error (no matching code, no catch-all) is still a failure.
        path_map[FAILURE_SINK] = FAILURE_SINK

        def router(state, _br=base_router, _tt=timer_target,
                   _ebc=error_by_code, _ca=catch_all_target, _tid=source_id):
            b = (state.get("boundary") or {}).get(_tid)
            if b:
                if b.get("kind") == "timer" and _tt is not None:
                    return _tt
                if b.get("kind") == "error":
                    code = b.get("code")
                    if code in _ebc:
                        return _ebc[code]
                    if _ca is not None:
                        return _ca
                    return FAILURE_SINK
            return _br(state)

        g.add_conditional_edges(source_id, router, path_map)

    # START → the start event's single successor
    start_out = model.outgoing(model.start_events[0])
    if len(start_out) != 1:
        raise CompilerError(f"startEvent must have exactly one outgoing flow, has {len(start_out)}")
    g.add_edge(START, resolve_node(start_out[0].target))

    # task + timer-catch + message-node edges (single outgoing each; event-gateway arms excluded)
    for element_id in node_ctxs:
        if element_id in arm_ids:
            continue
        single_out_edge(element_id)
    for cid in timer_catches:
        single_out_edge(cid)

    # parallel gateway edges: fork fans out to N successors; join edges to its single successor.
    for gw in parallels:
        for fl in model.outgoing(gw):
            g.add_edge(gw, resolve_node(fl.target))

    # ADR-031: event-based gateway → the winning arm's OUTGOING target. The gateway node sets
    # state.boundary[gw] = {"kind":"event","arm": arm_id}; route to that arm's downstream target.
    for gw, arms in event_gateways.items():
        arm_target = {}
        for arm in arms:
            outs = model.outgoing(arm)
            if len(outs) != 1:
                raise CompilerError(f"event-gateway arm '{arm}' must have exactly one outgoing flow")
            arm_target[arm] = resolve_node(outs[0].target)

        def _gw_router(state, _at=arm_target, _gw=gw):
            b = (state.get("boundary") or {}).get(_gw) or {}
            return _at.get(b.get("arm")) or FAILURE_SINK

        g.add_conditional_edges(gw, _gw_router, {**{t: t for t in arm_target.values()}, FAILURE_SINK: FAILURE_SINK})

    return g.compile(checkpointer=checkpointer)


def _make_end_node(end_id: str) -> Callable:
    def end_node(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"outcome": end_id}
    end_node.__name__ = f"end_{end_id}"
    return end_node


def _timer_catch_node(element_id: str) -> Callable:
    """A timer intermediate-catch event (ADR-027 Phase 2.2). On first entry ``interrupt`` parks the
    graph — the engine sees the ``kind:"timer"`` payload, registers a durable timer, and sets the
    instance WAITING_TIMER. When the poller fires it, the engine resumes with a signal and
    ``interrupt`` returns, so the node proceeds to its outgoing flow (no state change)."""
    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        interrupt({"kind": "timer", "timer_kind": "intermediate", "element_id": element_id})
        return {}
    node.__name__ = f"timer_{element_id}"
    return node


def _message_node(ctx, sub_kind: str) -> Callable:
    """A message intermediate-catch / receive task (ADR-031 Phase 2.4). On first entry ``interrupt``
    parks the graph — the engine registers a subscription and sets WAITING_MESSAGE. On a correlated
    delivery the engine resumes with the (already-validated) committed artifact, or the raw payload
    when the binding is a pure signal; the node writes it and proceeds."""
    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        resumed = interrupt({"kind": "message", "sub_kind": sub_kind,
                             "element_id": ctx.element_id, "message_name": ctx.message_name})
        delta: Dict[str, Any] = {
            "actor_log": [actor_entry(ctx.element_id, "external", "message")],
        }
        if isinstance(resumed, dict) and resumed.get("committed"):
            delta["artifacts"] = resumed["committed"]      # typed: validated + committed by the engine
        elif isinstance(resumed, dict) and "payload" in resumed:
            delta["messages"] = {ctx.element_id: resumed.get("payload")}  # untyped signal
        return delta
    node.__name__ = f"msg_{ctx.element_id}"
    return node


def _event_gateway_node(gw_id: str) -> Callable:
    """An event-based gateway (ADR-031 Phase 2.4 capstone). On entry ``interrupt`` parks the graph —
    the engine registers ALL arms (timer + message) and parks. The first arm to fire resumes here
    with ``{"arm": <arm_id>, ...}``; the node records the winner so the conditional edge routes to
    that arm's downstream target (the engine has already cancelled the losing arms)."""
    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        resumed = interrupt({"kind": "event_gateway", "element_id": gw_id})
        arm = resumed.get("arm") if isinstance(resumed, dict) else None
        delta: Dict[str, Any] = {
            "boundary": {gw_id: {"kind": "event", "arm": arm}},
            "actor_log": [actor_entry(arm or gw_id, (resumed or {}).get("actor", "external"),
                                      (resumed or {}).get("actor_kind", "message"))],
        }
        if isinstance(resumed, dict) and resumed.get("payload") is not None:
            delta["messages"] = {arm: resumed["payload"]}
        return delta
    node.__name__ = f"evgw_{gw_id}"
    return node


def _passthrough_node(gw_id: str) -> Callable:
    """A parallel gateway: no state change; edges do the fork/join (ADR-027 Phase 2.1)."""
    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        return {}
    node.__name__ = f"gw_{gw_id}"
    return node


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
