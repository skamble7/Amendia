# amendia_bpmn/compilability.py
"""The *structural executable-subset* rejections, in one place (ADR-027 §1a).

The agent-runtime compiler (`compile_graph`) refuses a handful of structural constructs it
cannot turn into a runnable LangGraph. The registry never runs the compiler (it validates +
activates), so without a shared gate a pack using these constructs could attach → assemble →
**activate** and only fail at runtime load. This function reproduces exactly those structural
rejections as error-severity :class:`Finding`s, so the registry's `PackValidator` (Stage 1) can
block activation off the same predicate the compiler raises off — they can never diverge.

Scope note: this covers only what makes a diagram *un-compilable*. Element-subset classification
(documented/unknown) and topology checks (dangling flows, reachability, start/end counts,
binding↔task bijection) live in `parse()` / the registry stages — not here.
"""
from __future__ import annotations

from typing import Dict, List, Set, Tuple

from amendia_bpmn.model import EXTENDED_TASK_KINDS, TASK_EXECUTOR_CATEGORY, BpmnModel, Finding
from amendia_bpmn.timers import timer_is_supported

# Execution profiles are the spec's two BPMN conformance levels (ADR-034 / Phase 2.8), an ordered
# hierarchy checked ``>=``. ``common_executable`` covers the whole built construct set — parallel,
# timers, error boundary, messages, sub-process, and every task kind. The granular per-construct
# levels (parallel/timers/…) were the incremental scaffold and are now RETIRED: kept as aliases to
# ``common_executable`` so persisted pins / older code resolve to the top level, and
# ``normalize_profile`` maps any retired value → ``common_executable`` so nothing pinned earlier
# fails to load. This is the SINGLE source of truth both services import (registry gate + pin,
# runtime compiler + load guard) so they can never diverge on "what runs where".
COMMON_SUBSET = "common_subset"
COMMON_EXECUTABLE = "common_executable"
EXECUTION_PROFILES: List[str] = [COMMON_SUBSET, COMMON_EXECUTABLE]

# Retired granular levels → the top level. Aliases keep the per-construct predicates below reading
# naturally (each ``needed = PARALLEL`` etc. resolves to ``common_executable``).
PARALLEL = TIMERS = ERROR_BOUNDARY = MESSAGES = SUBPROCESS = TASKS = COMMON_EXECUTABLE
_RETIRED = {"parallel", "timers", "error_boundary", "messages", "subprocess", "tasks"}


def normalize_profile(name: str) -> str:
    """Map a possibly-retired granular profile value → one of the two current levels. A persisted
    ``Resolution.required_execution_profile`` or an old env value like ``"timers"`` normalizes to
    ``common_executable`` (the top level satisfies every earlier granular pin)."""
    if name == COMMON_SUBSET:
        return COMMON_SUBSET
    if name == COMMON_EXECUTABLE or name in _RETIRED:
        return COMMON_EXECUTABLE
    raise ValueError(f"unknown execution profile '{name}' (known: {EXECUTION_PROFILES} + retired {_RETIRED})")


def profile_rank(name: str) -> int:
    """Ordinal of a profile in the hierarchy (normalizing retired names). Raises on an unknown."""
    return EXECUTION_PROFILES.index(normalize_profile(name))


def required_profile(model: BpmnModel) -> str:
    """The BPMN conformance level this model needs — DERIVED from the diagram, never operator-supplied
    (ADR-034 / Phase 2.8). ``common_executable`` iff the executable core uses ANY beyond-subset
    construct (reachability is enforced by ``parse``, so a captured construct is on the live path),
    else ``common_subset``. Inverse of ``compilability_findings`` ("what does this need to run?")."""
    beyond_subset = (
        model.parallel_gateways
        or model.timer_catch_events or model.boundary_timers
        or model.error_boundaries
        or model.message_catch_events or model.receive_tasks or model.event_based_gateways
        or model.subprocesses
        or any(k in EXTENDED_TASK_KINDS for k in model.tasks.values())
    )
    return COMMON_EXECUTABLE if beyond_subset else COMMON_SUBSET


def compilability_findings(model: BpmnModel, *, profile: str = COMMON_SUBSET) -> List[Finding]:
    """Error-severity findings for constructs the executable compiler cannot run under ``profile``."""
    profile = normalize_profile(profile)  # ADR-034: retired granular values → common_executable
    out: List[Finding] = []

    # parallelGateway is runnable only under the "parallel" profile (Phase 2.1). Under it, the
    # region must be structurally sound (balanced, block-structured, non-nested) — Phase 2.5.
    if model.parallel_gateways:
        if profile_rank(profile) < profile_rank(PARALLEL):
            out.append(Finding(
                "bpmn_parallel_gateway_unsupported",
                f"parallelGateway not supported for execution under profile '{profile}' "
                f"(activation requires the executable subset): {sorted(model.parallel_gateways)}",
                element_id=model.parallel_gateways[0], severity="error",
            ))
        else:
            out.extend(_parallel_structure_findings(model))

    # Timer constructs (Phase 2.2) run only under the "timers" profile. Under it, each must be
    # structurally sound (a supported schedule; a boundary timer attaches to a HITL userTask gate).
    if model.timer_catch_events or model.boundary_timers:
        if profile_rank(profile) < profile_rank(TIMERS):
            first = next(iter(model.timer_catch_events), None) or next(iter(model.boundary_timers), None)
            out.append(Finding(
                "bpmn_timer_unsupported",
                f"timer events not supported for execution under profile '{profile}' "
                f"(requires the '{TIMERS}' profile): "
                f"catch={sorted(model.timer_catch_events)} boundary_on={sorted(model.boundary_timers)}",
                element_id=first, severity="error",
            ))
        else:
            out.extend(_timer_structure_findings(model))

    # Error boundaries (Phase 2.3) run only under the "error_boundary" profile. Under it, each host's
    # boundaries must be unambiguous (no duplicate error_code, at most one catch-all).
    if model.error_boundaries:
        if profile_rank(profile) < profile_rank(ERROR_BOUNDARY):
            first_host = next(iter(model.error_boundaries))
            out.append(Finding(
                "bpmn_error_boundary_unsupported",
                f"error boundary events not supported for execution under profile '{profile}' "
                f"(requires the '{ERROR_BOUNDARY}' profile): boundary_on={sorted(model.error_boundaries)}",
                element_id=model.error_boundaries[first_host][0].id, severity="error",
            ))
        else:
            out.extend(_error_boundary_findings(model))

    # Message constructs (Phase 2.4) run only under the "messages" profile. Under it, an event-based
    # gateway's arms must all be catch events (message or timer).
    if model.message_catch_events or model.receive_tasks or model.event_based_gateways:
        if profile_rank(profile) < profile_rank(MESSAGES):
            first = (next(iter(model.message_catch_events), None) or next(iter(model.receive_tasks), None)
                     or next(iter(model.event_based_gateways), None))
            out.append(Finding(
                "bpmn_message_unsupported",
                f"message events / receive tasks / event-based gateways not supported for execution "
                f"under profile '{profile}' (requires the '{MESSAGES}' profile): "
                f"catch={sorted(model.message_catch_events)} receive={sorted(model.receive_tasks)} "
                f"event_gw={sorted(model.event_based_gateways)}",
                element_id=first, severity="error",
            ))
        else:
            out.extend(_message_structure_findings(model))

    # Embedded sub-processes (Phase 2.6) run only under the "subprocess" profile (they inline into the
    # parent graph). callActivity and sub-process boundary events are ALWAYS refused (deferred).
    for ca in model.call_activities:
        out.append(Finding(
            "bpmn_call_activity_unsupported",
            f"callActivity '{ca}' (reusable/called process) is not supported — cross-pack composition "
            f"is a separate design (deferred)",
            element_id=ca, severity="error"))
    for bid in model.subprocess_boundaries:
        out.append(Finding(
            "bpmn_subprocess_boundary_unsupported",
            f"boundary event '{bid}' on a sub-process is not supported yet (deferred, like "
            f"timer-boundary-on-serviceTask)",
            element_id=bid, severity="error"))
    if model.subprocesses and profile_rank(profile) < profile_rank(SUBPROCESS):
        out.append(Finding(
            "bpmn_subprocess_unsupported",
            f"embedded sub-process not supported for execution under profile '{profile}' "
            f"(requires the '{SUBPROCESS}' profile): {sorted(model.subprocesses)}",
            element_id=next(iter(model.subprocesses)), severity="error"))

    # Extended task kinds (Phase 2.7) run only under the "tasks" profile. An inline <script> body on a
    # scriptTask is ALWAYS refused (arbitrary code violates the capability/audit model — bind a skill).
    for sid in model.inline_scripts:
        out.append(Finding(
            "bpmn_inline_script_unsupported",
            f"scriptTask '{sid}' has an inline <script> body, which is not executed — bind a skill "
            f"capability instead (arbitrary inline code is refused by the capability/audit model)",
            element_id=sid, severity="error"))
    extended_used = sorted(tid for tid, k in model.tasks.items() if k in EXTENDED_TASK_KINDS)
    if extended_used and profile_rank(profile) < profile_rank(TASKS):
        out.append(Finding(
            "bpmn_task_kind_unsupported",
            f"send/script/manual/businessRule tasks not supported for execution under profile "
            f"'{profile}' (requires the '{TASKS}' profile): {extended_used}",
            element_id=extended_used[0], severity="error"))

    # A gateway may only be reached from a task, never target another gateway.
    gateways = set(model.exclusive_gateways) | set(model.parallel_gateways)
    for fl in model.flows:
        if fl.source in gateways and fl.target in gateways:
            out.append(Finding(
                "bpmn_chained_gateway_unsupported",
                f"chained gateways not supported: gateway '{fl.source}' flows directly into "
                f"gateway '{fl.target}'",
                element_id=fl.source, severity="error",
            ))

    # Exactly one outgoing flow per task (the router/edge is single-valued).
    for tid in model.tasks:
        n = len(model.outgoing(tid))
        if n != 1:
            out.append(Finding(
                "bpmn_task_outgoing_arity",
                f"task '{tid}' must have exactly one outgoing flow, has {n}",
                element_id=tid, severity="error",
            ))

    # Exactly one outgoing flow from the start event.
    for sid in model.start_events:
        n = len(model.outgoing(sid))
        if n != 1:
            out.append(Finding(
                "bpmn_start_outgoing_arity",
                f"startEvent '{sid}' must have exactly one outgoing flow, has {n}",
                element_id=sid, severity="error",
            ))

    return out


def _timer_structure_findings(model: BpmnModel) -> List[Finding]:
    """Structural validation of timer constructs under the ``timers`` profile (Phase 2.2).

    Enforces: a timer intermediate catch carries a resolvable schedule; a timer boundary event
    carries a resolvable schedule AND attaches to a ``userTask`` (the HITL gate it guards). A
    boundary on a ``serviceTask`` (interrupting a mid-flight synchronous capability) is a KNOWN,
    intentionally deferred limitation — rejected here so it can't activate under this rung."""
    out: List[Finding] = []
    for cid, td in model.timer_catch_events.items():
        if not timer_is_supported(td):
            out.append(Finding(
                "bpmn_timer_unsupported",
                f"timer intermediate catch '{cid}' has no resolvable schedule "
                f"(need timeDuration/timeDate; timeCycle is not supported)",
                element_id=cid, severity="error"))
    for host, bt in model.boundary_timers.items():
        if not timer_is_supported(bt.timer):
            out.append(Finding(
                "bpmn_timer_unsupported",
                f"timer boundary '{bt.id}' has no resolvable schedule "
                f"(need timeDuration/timeDate; timeCycle is not supported)",
                element_id=bt.id, severity="error"))
        # The boundary guards a HITL gate — any human-category host (userTask or manualTask). A
        # boundary on a capability serviceTask (interrupting a mid-flight capability) stays deferred.
        if TASK_EXECUTOR_CATEGORY.get(model.tasks.get(host)) != "human":
            out.append(Finding(
                "bpmn_timer_boundary_host_unsupported",
                f"timer boundary '{bt.id}' attaches to '{host}' — only a HITL gate (userTask/manualTask) "
                f"is supported (boundary on a serviceTask is a deferred limitation)",
                element_id=bt.id, severity="error"))
    return out


def _message_structure_findings(model: BpmnModel) -> List[Finding]:
    """Structural validation of message constructs under the ``messages`` profile (Phase 2.4): an
    event-based gateway must have arms and every arm must be a catch event (message or timer)."""
    out: List[Finding] = []
    catch_like = set(model.message_catch_events) | set(model.timer_catch_events)
    for gw, arms in model.event_based_gateways.items():
        if not arms:
            out.append(Finding("bpmn_event_gateway_no_arms",
                               f"event-based gateway '{gw}' has no outgoing arms", element_id=gw, severity="error"))
        for a in arms:
            if a not in catch_like:
                out.append(Finding("bpmn_event_gateway_arm_not_catch",
                                   f"event-based gateway '{gw}' arm '{a}' is not a message/timer catch event",
                                   element_id=gw, severity="error"))
    return out


def _error_boundary_findings(model: BpmnModel) -> List[Finding]:
    """Structural validation of error boundary events under the ``error_boundary`` profile (Phase 2.3):
    on a given host, no two boundaries may catch the same ``error_code``, and at most one may be a
    catch-all (no ``errorRef``) — otherwise routing on a raised code would be ambiguous."""
    out: List[Finding] = []
    for host, ebs in model.error_boundaries.items():
        seen: Set[str] = set()
        catch_alls = 0
        for eb in ebs:
            if eb.error_code is None:
                catch_alls += 1
            elif eb.error_code in seen:
                out.append(Finding(
                    "bpmn_error_boundary_ambiguous",
                    f"host '{host}' has two error boundaries catching the same code '{eb.error_code}'",
                    element_id=eb.id, severity="error"))
            else:
                seen.add(eb.error_code)
        if catch_alls > 1:
            out.append(Finding(
                "bpmn_error_boundary_ambiguous",
                f"host '{host}' has {catch_alls} catch-all error boundaries (at most one allowed)",
                element_id=ebs[0].id, severity="error"))
    return out


def _parallel_structure_findings(model: BpmnModel) -> List[Finding]:
    """Structural validation of parallel regions under the ``parallel`` profile (Phase 2.5).

    Enforces: every gateway is a pure fork (≥2 out / 1 in) or pure join (≥2 in / 1 out); forks and
    joins balance; each fork's branches converge at exactly one join whose in-degree matches the
    fork's out-degree (block-structured, no interleaving); nested parallel scopes are rejected
    (a known limitation for this phase). Errors block activation + compile."""
    out: List[Finding] = []
    parallels: Set[str] = set(model.parallel_gateways)
    flows_by_source: Dict[str, List] = {}
    in_count: Dict[str, int] = {}
    for fl in model.flows:
        flows_by_source.setdefault(fl.source, []).append(fl)
        in_count[fl.target] = in_count.get(fl.target, 0) + 1

    forks: Set[str] = set()
    joins: Set[str] = set()
    for gw in parallels:
        outc = len(model.outgoing(gw))
        inc = in_count.get(gw, 0)
        if outc >= 2 and inc >= 2:
            out.append(Finding("bpmn_parallel_unstructured",
                               f"parallel gateway '{gw}' is both a fork and a join ({inc} in / {outc} out) — not supported",
                               element_id=gw, severity="error"))
        elif outc >= 2:
            forks.add(gw)
        elif inc >= 2:
            joins.add(gw)
        else:
            out.append(Finding("bpmn_parallel_unbalanced",
                               f"parallel gateway '{gw}' has {inc} in / {outc} out — a fork needs ≥2 out, a join ≥2 in",
                               element_id=gw, severity="error"))

    if len(forks) != len(joins):
        out.append(Finding("bpmn_parallel_unbalanced",
                           f"unbalanced parallel regions: {len(forks)} fork(s) vs {len(joins)} join(s)",
                           element_id=(sorted(forks) or sorted(joins) or [None])[0], severity="error"))

    for f in sorted(forks):
        branch_joins: Set[str] = set()
        nested = False
        for bf in model.outgoing(f):
            js, saw_fork = _reach_join(bf.target, parallels, forks, flows_by_source)
            nested = nested or saw_fork
            branch_joins |= js
        if nested:
            out.append(Finding("bpmn_parallel_nested_unsupported",
                               f"parallel region from fork '{f}' contains a nested fork — nested parallel is not supported",
                               element_id=f, severity="error"))
        elif len(branch_joins) != 1:
            out.append(Finding("bpmn_parallel_unstructured",
                               f"fork '{f}' branches do not converge at a single join (reached {sorted(branch_joins)})",
                               element_id=f, severity="error"))
        else:
            j = next(iter(branch_joins))
            if in_count.get(j, 0) != len(model.outgoing(f)):
                out.append(Finding("bpmn_parallel_unstructured",
                                   f"fork '{f}' ({len(model.outgoing(f))} branches) and join '{j}' "
                                   f"({in_count.get(j, 0)} incoming) do not match — interleaved region",
                                   element_id=f, severity="error"))
    return out


def _reach_join(start: str, parallels: Set[str], forks: Set[str],
                flows_by_source: Dict[str, List]) -> Tuple[Set[str], bool]:
    """From a fork branch head, BFS downstream until each path hits a parallel gateway. Returns the
    set of parallel *joins* reached (stopping there) and whether a nested *fork* was encountered."""
    joins: Set[str] = set()
    saw_fork = False
    seen: Set[str] = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur in parallels:
            if cur in forks:
                saw_fork = True          # nested fork inside a branch — do not traverse past it
            else:
                joins.add(cur)           # a join — stop this path here
            continue
        for fl in flows_by_source.get(cur, []):
            stack.append(fl.target)
    return joins, saw_fork
