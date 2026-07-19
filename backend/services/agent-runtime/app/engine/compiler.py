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
import time
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from amendia_bpmn import compilability_findings, parse_iso_duration
from app.engine import expr
from app.engine.bundle import PackBundle, build_node_contexts
from app.engine.call_activity import (
    BundleProvider,
    CallActivityError,
    flatten_call_activities,
    make_map_node,
)
from app.engine.compensation import make_compensation_driver, make_compensation_router
from app.engine.executor import Executor
from app.engine.multi_instance import (
    make_mi_dispatch_node,
    make_mi_fan_out,
    make_mi_iteration_node,
    make_mi_join_node,
    make_sequential_mi_node,
    mi_node_ids,
)
from app.engine.state import ProcessState, actor_entry
from app.engine.task_runner import make_task_node

logger = logging.getLogger(__name__)

FAILURE_SINK = "__failure__"
FAILED_OUTCOME = "__failed__"


class CompilerError(Exception):
    """The pack cannot be compiled to a runnable graph."""


def compile_graph(bundle: PackBundle, executor: Executor, *, simulation: bool, checkpointer,
                  profile: str = "common_subset", bundle_provider: Optional[BundleProvider] = None,
                  clock: Optional[Callable[[], float]] = None):
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

    # ADR-039: inline-compile any callActivity by splicing the pinned callee's graph in (identity for a
    # single-pack — model/node_ctxs are byte-unchanged and boundary_maps is empty).
    try:
        model, node_ctxs, boundary_maps = flatten_call_activities(bundle, bundle_provider)
    except CallActivityError as exc:
        raise CompilerError(f"{exc} (pack {bundle.pack_key}@{bundle.pack_version})") from exc
    map_node_ids = set(boundary_maps)
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
    mi_hosts = set(model.multi_instance)                         # ADR-036: multi-instance task hosts
    # ADR-041: boundary events on a subProcess (a scope). A **timer** boundary → a scope-wide SLA (a
    # scope-entry node stamps a deadline; every inner node enforces the remaining budget and diverts the
    # whole scope on breach); an **error** boundary → a routing fallback for an inner node's unmatched
    # modeled error. (callActivity boundaries stay deferred — ADR-039.)
    # ADR-042 (Item F): event sub-processes are scope-wide handlers whose enclosing scope may be a
    # subProcess OR the whole process. The parser has already registered a runnable ESP's handler onto
    # boundary_timers / error_boundaries[enclosing_scope] (reusing the ADR-041 router), so here we only
    # GENERALIZE the scope sets to also recognize a **process-level** scope (which a real boundary can
    # never target). We also need: the ESP body nodes (the handler — excluded from scope handlers +
    # given terminal ends), and the ESP body ends (added as END nodes).
    esp_scopes = {esp.enclosing_scope for esp in model.event_subprocesses.values() if esp.unsupported is None}

    def _is_scope(sid: str) -> bool:
        return sid in model.subprocesses or sid in esp_scopes

    subproc_timers = {sid: bt for sid, bt in model.boundary_timers.items() if _is_scope(sid)}
    subproc_errors = {sid: ebs for sid, ebs in model.error_boundaries.items() if _is_scope(sid)}
    scope_entry_ids = {sid: f"{sid}__sla_entry" for sid in subproc_timers}
    process_timer_scope = model.process_id if model.process_id in subproc_timers else None
    esp_end_ids = {e for esp in model.event_subprocesses.values() if esp.unsupported is None
                   for e in esp.end_ids}
    ends |= esp_end_ids  # an ESP body's ends are terminal (they end the instance)
    # ADR-043 (Item G): compensation. A compensation HANDLER activity is OFF the sequence flow (invoked
    # inline by the compensate-throw driver, never a graph node / never wired). A compensate THROW event
    # compiles to a self-looping driver node (terminal end-throws are NOT plain end nodes). A compensable
    # PRIMARY carries its handler id + scope so its task node logs a compensation entry on commit.
    comp_handler_ids = set(model.compensation_handlers)
    comp_throw_ids = set(model.compensate_throws)
    end_throw_ids = {tid for tid, thr in model.compensate_throws.items() if thr.is_end}

    def _in_esp_body(eid: str) -> bool:
        """True iff ``eid`` lives inside an event sub-process body (its scope chain passes through an
        ESP id). The ESP body IS the handler, so it is never itself subject to a scope handler."""
        s = eid
        seen: set = set()
        while s and s not in seen:
            seen.add(s)
            if s in model.event_subprocesses:
                return True
            s = model.element_scope.get(s)
        return False

    def _enclosing_scopes(eid: str) -> List[str]:
        """The scopes containing ``eid``, inner-most first (walks ``element_scope`` outward). A
        subProcess scope is yielded when it carries a boundary/ESP handler; the **whole process** is
        yielded last when a process-level event sub-process guards it (ADR-042). An ESP body node is
        the handler itself — never under any scope handler (nested ESP is deferred)."""
        if _in_esp_body(eid):
            return []
        out: List[str] = []
        s = model.element_scope.get(eid)
        while s and s != model.process_id and s in model.subprocesses:
            out.append(s)
            s = model.element_scope.get(s)
        if model.process_id in subproc_timers or model.process_id in subproc_errors:
            out.append(model.process_id)
        return out

    # every task must be bound (message catch/receive are also in node_ctxs — bound via message binding)
    missing = tasks - set(node_ctxs)
    if missing:
        raise CompilerError(f"unbound BPMN tasks (no manifest binding): {sorted(missing)}")

    # ADR-043 (Item G): the compensation handler NodeContexts the driver invokes inline, and — on each
    # compensable primary's node context — its handler id + enclosing scope, so the task runner appends a
    # compensation-log entry when the primary commits its side effect.
    handler_ctxs = {hid: node_ctxs[hid] for hid in comp_handler_ids if hid in node_ctxs}
    for primary, handler in model.compensations.items():
        if primary in node_ctxs:
            node_ctxs[primary].compensate_handler_id = handler
            node_ctxs[primary].compensate_scope = model.element_scope.get(primary, model.process_id)

    g = StateGraph(ProcessState)

    def _running_deadline(element_id, ctx):
        """ADR-040: the interrupting timer boundary a running serviceTask self-enforces, or None. Only
        an autonomous (hitl none), read_only capability host qualifies; a HITL host (userTask/manualTask)
        uses the ADR-029 idle-gate path (no in-process deadline). Refuse the unsafe combinations."""
        bt = model.boundary_timers.get(element_id)
        if bt is None or ctx.executor_type != "capability":
            return None
        if ctx.hitl_mode != "none":
            raise CompilerError(
                f"timer boundary on '{element_id}': only an autonomous (hitl 'none') capability "
                f"serviceTask self-enforces a running deadline (ADR-040)")
        se = ctx.descriptor.side_effect if ctx.descriptor is not None else None
        if (se.value if hasattr(se, "value") else se) == "side_effectful":
            raise CompilerError(
                f"timer boundary on '{element_id}': interrupting a side-effectful capability is unsafe "
                f"(compensation — deferred to Item G); only read_only is supported (ADR-040)")
        return bt

    def _scope_timers_for(element_id, ctx):
        """ADR-041: the enclosing subProcess timer scopes ``[(scope_id, duration_seconds)]`` this node
        runs under. An interrupting timer scope may contain only autonomous read_only capabilities —
        a HITL gate or a side-effectful task inside it is refused (fail-closed; the registry validates
        the same cross-contract rule)."""
        scopes = [s for s in _enclosing_scopes(element_id) if s in subproc_timers]
        if scopes:
            if ctx.executor_type == "human":
                raise CompilerError(
                    f"HITL gate '{element_id}' inside an interrupting-timer subProcess is not supported "
                    f"(the parked-gate SLA is ADR-029, not scope cancellation; ADR-041)")
            se = ctx.descriptor.side_effect if ctx.descriptor is not None else None
            if (se.value if hasattr(se, "value") else se) == "side_effectful":
                raise CompilerError(
                    f"side-effectful task '{element_id}' inside an interrupting-timer subProcess is unsafe "
                    f"(cancelling committed side effects is compensation — deferred to Item G; ADR-041)")
        return [(s, parse_iso_duration(subproc_timers[s].timer.value).total_seconds()) for s in scopes]

    for element_id, ctx in node_ctxs.items():
        if (element_id in message_nodes or element_id in arm_ids or element_id in mi_hosts
                or element_id in comp_handler_ids):
            continue  # message → message node; arms → gateway; MI → dispatch/iter/join; comp handler → inline
        g.add_node(element_id, make_task_node(ctx, executor, simulation=simulation,
                                              boundary_timer=_running_deadline(element_id, ctx), clock=clock,
                                              scope_timers=_scope_timers_for(element_id, ctx)))

    for end_id in model.end_events:
        if end_id in end_throw_ids:
            continue  # ADR-043: a terminal compensate-throw endEvent compiles to a driver, not an end node
        g.add_node(end_id, _make_end_node(end_id))
        g.add_edge(end_id, END)

    # ADR-042: an event sub-process body's ends are terminal too — mark the outcome and edge to END
    # (the ESP is the handler; once it completes the instance is done).
    for end_id in esp_end_ids:
        g.add_node(end_id, _make_end_node(end_id))
        g.add_edge(end_id, END)

    # ADR-043 (Item G): each compensate-throw event → a self-looping driver node that compensates its
    # scope's completed compensable activities in reverse (LIFO) order (see app.engine.compensation).
    for tid in comp_throw_ids:
        thr = model.compensate_throws[tid]
        g.add_node(tid, make_compensation_driver(tid, thr.scope, model.process_id, handler_ctxs,
                                                 executor, simulation=simulation))

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

    # Multi-instance hosts (ADR-036): a bound task that runs N times. Sequential → one guarded loop
    # node; parallel → a dispatch node (fans out one Send per iteration), an iteration node (runs one),
    # and a join barrier (aggregates in index order). The host id stays the ENTRY node either way, so
    # incoming flows resolve to it unchanged. HITL-gated / boundary-carrying MI hosts are refused.
    for host in mi_hosts:
        mi = model.multi_instance[host]
        mctx = node_ctxs[host]
        if mctx.executor_type != "capability" or mctx.descriptor is None:
            raise CompilerError(f"multi-instance host '{host}' must bind a capability executor")
        if mctx.hitl_mode != "none":
            raise CompilerError(
                f"multi-instance host '{host}' has HITL mode '{mctx.hitl_mode}' — HITL-gated "
                f"multi-instance is not supported yet (iterations run autonomously)")
        if host in model.boundary_timers or host in model.error_boundaries:
            raise CompilerError(
                f"multi-instance host '{host}' also carries a boundary event — MI + boundary is "
                f"not supported yet")
        if mi.completion_condition:
            try:
                expr.parse_condition(mi.completion_condition)  # validate at compile time (like gateways)
            except expr.ConditionSyntaxError as exc:
                raise CompilerError(f"multi-instance host '{host}': completionCondition {exc}") from exc
        if mi.is_sequential:
            g.add_node(host, make_sequential_mi_node(mctx, executor, simulation=simulation,
                                                     host=host, mi=mi))
        else:
            iter_id, join_id = mi_node_ids(host)
            g.add_node(host, make_mi_dispatch_node(host))
            g.add_node(iter_id, make_mi_iteration_node(mctx, executor, simulation=simulation,
                                                       host=host, mi=mi))
            g.add_node(join_id, make_mi_join_node(mctx, host=host, mi=mi))

    # ADR-039: callActivity input/output boundary-map nodes (pure state-copy at the callee boundary).
    for mid, mnode in boundary_maps.items():
        g.add_node(mid, make_map_node(mnode))

    # ADR-041: scope-entry nodes stamp a subProcess timer-boundary's scope-wide SLA deadline on entry.
    for sid, entry_id in scope_entry_ids.items():
        _dur = parse_iso_duration(subproc_timers[sid].timer.value).total_seconds()
        g.add_node(entry_id, _scope_entry_node(sid, _dur, clock or time.monotonic))

    g.add_node(FAILURE_SINK, _failure_node)
    g.add_edge(FAILURE_SINK, END)

    # ADR-032 Phase 2.6: inline embedded sub-processes. A flow targeting a subProcess box routes to
    # its start's successor; a flow targeting an internal (nested) end routes to the box's parent-level
    # outgoing target. Both recurse (nested sub-processes), so the whole scope is flattened into one
    # graph and the sub-process start/end become edges, not nodes.
    end_to_sub = {eid: sub for sub in model.subprocesses.values() for eid in sub.end_ids}

    def resolve_node(target: str) -> str:
        if target in model.subprocesses:
            # ADR-041: a subProcess with a timer boundary is entered via its scope-entry (SLA-stamp) node.
            if target in scope_entry_ids:
                return scope_entry_ids[target]
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
                or target in message_nodes or target in event_gateways or target in map_node_ids
                or target in comp_throw_ids):  # ADR-043: a compensate-throw driver is a valid flow target
            return target
        if target in gateways:
            raise CompilerError(f"chained gateways not supported (target '{target}' is a gateway)")
        raise CompilerError(f"flow targets unknown/unsupported node '{target}'")

    def _error_chain(ebs):
        """(error_code -> target, catch_all_target_or_None) for a list of error boundaries."""
        by_code: Dict[str, str] = {}
        ca = None
        for eb in ebs:
            t = resolve_node(eb.target)
            if eb.error_code is None:
                ca = t
            else:
                by_code[eb.error_code] = t
        return by_code, ca

    def single_out_edge(source_id: str) -> None:
        """Wire a single-outgoing node: a direct edge / exclusive-gateway router, with boundary-event
        exits layered on top, read from the unified ``state.boundary`` channel. A node's OWN timer
        boundary (ADR-029/040) and error boundaries (ADR-030) route on ``boundary[source]``; ADR-041 adds
        the **enclosing subProcess scope**'s boundaries — an unmatched modeled error falls back to each
        enclosing scope's error handler (inner→outer) before ``FAILURE_SINK``, and a scope timer breach
        (``boundary[scope_id]``, set by any inner node) diverts the whole scope to its timer target."""
        outs = model.outgoing(source_id)
        if len(outs) != 1:
            raise CompilerError(f"node '{source_id}' must have exactly one outgoing flow, has {len(outs)}")
        target = outs[0].target
        timer_boundary = model.boundary_timers.get(source_id)
        own_errors = model.error_boundaries.get(source_id, [])
        enclosing = _enclosing_scopes(source_id)
        scope_err_chains = [_error_chain(subproc_errors[s]) for s in enclosing if s in subproc_errors]
        scope_timer_targets = [(s, resolve_node(subproc_timers[s].target))
                               for s in enclosing if s in subproc_timers]
        is_gateway = target in gateways

        if (timer_boundary is None and not own_errors and not scope_err_chains and not scope_timer_targets):
            # No boundary of any kind: a plain edge, or an exclusive-gateway router (byte-unchanged).
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

        timer_target = resolve_node(timer_boundary.target) if timer_boundary is not None else None
        if timer_target is not None:
            path_map[timer_target] = timer_target
        # Error chains: the node's own boundaries first, then each enclosing scope (inner→outer).
        error_chains = ([_error_chain(own_errors)] if own_errors else []) + scope_err_chains
        for by_code, ca in error_chains:
            for t in by_code.values():
                path_map[t] = t
            if ca is not None:
                path_map[ca] = ca
        for _sid, starget in scope_timer_targets:
            path_map[starget] = starget
        path_map[FAILURE_SINK] = FAILURE_SINK

        def router(state, _br=base_router, _tt=timer_target, _chains=error_chains,
                   _scopes=scope_timer_targets, _tid=source_id):
            b = (state.get("boundary") or {}).get(_tid)
            if b:
                if b.get("kind") == "timer" and _tt is not None:
                    return _tt
                if b.get("kind") == "error":
                    code = b.get("code")
                    for by_code, ca in _chains:   # own, then enclosing scopes (inner→outer)
                        if code in by_code:
                            return by_code[code]
                        if ca is not None:
                            return ca
                    return FAILURE_SINK
            # ADR-041: a scope timer breach marked by ANY inner node diverts the whole scope.
            bd = state.get("boundary") or {}
            for scope_id, starget in _scopes:
                sb = bd.get(scope_id)
                if sb and sb.get("kind") == "timer":
                    return starget
            return _br(state)

        g.add_conditional_edges(source_id, router, path_map)

    # START → the start event's single successor. ADR-042: a process-level timer event sub-process
    # makes the WHOLE PROCESS a timer scope — its SLA deadline is stamped at the process entry, so the
    # START edge goes through that scope-entry node first (there is no subProcess box to stamp at).
    start_out = model.outgoing(model.start_events[0])
    if len(start_out) != 1:
        raise CompilerError(f"startEvent must have exactly one outgoing flow, has {len(start_out)}")
    first_node = resolve_node(start_out[0].target)
    if process_timer_scope is not None:
        entry = scope_entry_ids[process_timer_scope]
        g.add_edge(START, entry)
        g.add_edge(entry, first_node)
    else:
        g.add_edge(START, first_node)

    # ADR-041: each subProcess scope-entry (SLA-stamp) node → the subProcess's start-successor (the
    # first inner node). The process-level scope-entry (ADR-042) is wired from START above, not here.
    for sid, entry_id in scope_entry_ids.items():
        if sid == model.process_id:
            continue
        sub = model.subprocesses[sid]
        souts = model.outgoing(sub.start_id) if sub.start_id else []
        if len(souts) != 1:
            raise CompilerError(f"sub-process '{sid}' start must have exactly one outgoing flow")
        g.add_edge(entry_id, resolve_node(souts[0].target))

    # task + timer-catch + message-node edges (single outgoing each; event-gateway arms + MI hosts +
    # off-flow compensation handlers excluded — handlers are invoked inline by the compensate-throw driver)
    for element_id in node_ctxs:
        if element_id in arm_ids or element_id in mi_hosts or element_id in comp_handler_ids:
            continue
        single_out_edge(element_id)
    for cid in timer_catches:
        single_out_edge(cid)

    # ADR-043 (Item G): wire each compensate-throw driver. It self-loops while any compensation is pending
    # in its scope, then proceeds to its continuation: an intermediate throw's single outgoing successor,
    # or a terminal end node (outcome = the throw id) for an end-event throw.
    for tid in comp_throw_ids:
        thr = model.compensate_throws[tid]
        if thr.is_end:
            done_node = f"{tid}__done"
            g.add_node(done_node, _make_end_node(tid))
            g.add_edge(done_node, END)
            done_target = done_node
        else:
            outs = model.outgoing(tid)
            if len(outs) != 1:
                raise CompilerError(f"compensate throw '{tid}' must have exactly one outgoing flow, has {len(outs)}")
            done_target = resolve_node(outs[0].target)
        router = make_compensation_router(tid, thr.scope, model.process_id, done_target)
        g.add_conditional_edges(tid, router, {tid: tid, done_target: done_target})
    # ADR-039: each callActivity boundary-map node has exactly one outgoing (in → callee entry; out →
    # the callActivity's parent target) — wire it like any single-outgoing node.
    for mid in map_node_ids:
        single_out_edge(mid)

    # Multi-instance edges (ADR-036). Sequential: the loop node keeps the host's single outgoing.
    # Parallel: dispatch --Send(per iteration)--> iter --> join (barrier), then the JOIN keeps the
    # host's single outgoing (a plain edge or the exclusive-gateway router — same as any task).
    def _wire_mi_out(from_node: str, host: str) -> None:
        outs = model.outgoing(host)
        if len(outs) != 1:
            raise CompilerError(
                f"multi-instance host '{host}' must have exactly one outgoing flow, has {len(outs)}")
        target = outs[0].target
        if target in gateways:
            router, path_map = _build_gateway_router(bundle, model, target, resolve_node)
            g.add_conditional_edges(from_node, router, path_map)
        else:
            g.add_edge(from_node, resolve_node(target))

    for host in mi_hosts:
        mi = model.multi_instance[host]
        if mi.is_sequential:
            _wire_mi_out(host, host)
        else:
            iter_id, join_id = mi_node_ids(host)
            g.add_conditional_edges(host, make_mi_fan_out(host, mi), [iter_id, join_id])
            g.add_edge(iter_id, join_id)
            _wire_mi_out(join_id, host)

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


def _scope_entry_node(scope_id: str, duration: float, clock: Callable[[], float]) -> Callable:
    """ADR-041: the entry to a subProcess with a timer boundary — stamps the scope-wide SLA deadline
    (absolute, injected clock) into ``state.scope_deadlines[scope_id]`` so every inner node enforces the
    remaining budget. Re-runs (recovery) re-stamp a fresh deadline (same semantic as ADR-040)."""
    _clock = clock or time.monotonic

    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"scope_deadlines": {scope_id: _clock() + duration}}
    node.__name__ = f"scope_entry_{scope_id}"
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
