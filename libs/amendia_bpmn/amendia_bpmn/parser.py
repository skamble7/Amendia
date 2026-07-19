# amendia_bpmn/parser.py
"""BPMN 2.0 parsing + subset/well-formedness checks (stdlib ElementTree).

Extracts the executable elements the registry validation stages and the runtime
graph compiler need, and reports structural findings. Only the Iteration-1
element subset is allowed. This is the single source of truth for the supported
subset; the process-registry wraps it into its ValidationReport and the
agent-runtime compiles the returned BpmnModel into a LangGraph StateGraph.

The sha256 comparison is deliberately NOT done here — it is manifest-coupled and
belongs to the registry caller (use ``compute_sha256`` for that).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple
from xml.etree import ElementTree as ET

from amendia_bpmn.model import (
    EXECUTABLE_KINDS,
    EXTENDED_TASK_KINDS,
    IGNORE_CHILDREN,
    NODE_KINDS,
    RECOGNIZED_NON_EXECUTABLE,
    TASK_KINDS,
    DEFAULT_CALL_VERSION_RANGE,
    BoundaryTimer,
    BpmnModel,
    CallActivity,
    ClassifiedElement,
    CompensateThrow,
    CompensationHandler,
    ErrorBoundary,
    EventSubProcess,
    Finding,
    Flow,
    MultiInstance,
    SubProcess,
    TimerDef,
    local_name,
)
from amendia_bpmn.compilability import normalize_profile
from amendia_bpmn.timers import timer_is_supported

# Sentinel: a boundaryEvent carries an errorEventDefinition with no errorRef → a catch-all boundary.
_CATCH_ALL = object()


def _error_ref(el):
    """If a flow node carries an ``errorEventDefinition``, return its ``errorRef`` (or ``_CATCH_ALL``
    when it has none). Returns ``None`` when there is no error definition (so non-error boundary
    events fall through to their own handling)."""
    eed = next((c for c in el if local_name(c.tag) == "errorEventDefinition"), None)
    if eed is None:
        return None
    return eed.get("errorRef") or _CATCH_ALL


def _has_message_def(el) -> bool:
    """True iff a flow node carries a ``messageEventDefinition`` (ADR-031)."""
    return any(local_name(c.tag) == "messageEventDefinition" for c in el)


def _compensate_def(el):
    """The ``compensateEventDefinition`` child of a boundary/throw event, or ``None`` (ADR-043)."""
    return next((c for c in el if local_name(c.tag) == "compensateEventDefinition"), None)


def _has_cancel_def(el) -> bool:
    """True iff an event carries a ``cancelEventDefinition`` (a transaction cancel — deferred, ADR-043)."""
    return any(local_name(c.tag) == "cancelEventDefinition" for c in el)


def _message_ref(el) -> Optional[str]:
    """The ``messageRef`` on a node's ``messageEventDefinition`` (or the node's own ``messageRef``
    attr for a receiveTask), used to look up the BPMN ``<bpmn:message name>``. Advisory only."""
    for c in el:
        if local_name(c.tag) == "messageEventDefinition" and c.get("messageRef"):
            return c.get("messageRef")
    return el.get("messageRef")


def _local_attr(el, name: str) -> Optional[str]:
    """First attribute value whose *local* name equals ``name`` — namespace-agnostic so an Amendia
    extension attribute (``amendia:aggregation``), a camunda one, or a bare attribute all resolve
    (ElementTree keys namespaced attrs as ``{uri}name``)."""
    for k, v in el.attrib.items():
        if local_name(k) == name:
            return v
    return None


def _multi_instance(el, host_id: str, *, on_subprocess: bool) -> Optional[MultiInstance]:
    """Build a :class:`MultiInstance` from an activity's ``<multiInstanceLoopCharacteristics>`` child,
    or ``None`` if the activity carries none (ADR-036). Reads ``isSequential``; ``loopCardinality`` /
    ``loopDataInputRef`` (bound on N); ``inputDataItem``/``elementVariable`` (per-item var);
    ``completionCondition``; and the ``amendia:aggregation`` ext attribute (``list`` default | ``indexed``)."""
    mi_el = next((c for c in el if local_name(c.tag) == "multiInstanceLoopCharacteristics"), None)
    if mi_el is None:
        return None
    cardinality: Optional[int] = None
    collection_ref: Optional[str] = None
    item_name: Optional[str] = None
    completion: Optional[str] = None
    for c in mi_el:
        ln = local_name(c.tag)
        if ln == "loopCardinality":
            txt = (c.text or "").strip()
            try:
                cardinality = int(txt)
            except (TypeError, ValueError):
                cardinality = None
        elif ln == "loopDataInputRef":
            collection_ref = (c.text or "").strip() or None
        elif ln == "inputDataItem":
            item_name = c.get("name") or (c.text or "").strip() or None
        elif ln == "completionCondition":
            completion = (c.text or "").strip() or None
    collection_ref = collection_ref or _local_attr(mi_el, "collection")
    item_name = item_name or _local_attr(mi_el, "elementVariable")
    agg = (_local_attr(mi_el, "aggregation") or _local_attr(el, "aggregation") or "list").lower()
    if agg not in ("list", "indexed"):
        agg = "list"
    return MultiInstance(
        attached_to=host_id, is_sequential=(mi_el.get("isSequential") == "true"),
        cardinality=cardinality, collection_ref=collection_ref, item_name=item_name,
        completion_condition=completion, aggregation=agg, on_subprocess=on_subprocess,
    )


def _timer_def(el) -> Optional[TimerDef]:
    """A flow node's ``timerEventDefinition`` schedule, or ``None`` if it carries no timer definition
    (so non-timer catch/boundary events fall through to the ``documented`` classification)."""
    ted = next((c for c in el if local_name(c.tag) == "timerEventDefinition"), None)
    if ted is None:
        return None
    for spec in ted:
        ln = local_name(spec.tag)
        if ln == "timeDuration":
            return TimerDef("duration", (spec.text or "").strip() or None)
        if ln == "timeDate":
            return TimerDef("date", (spec.text or "").strip() or None)
        if ln == "timeCycle":
            return TimerDef("cycle", (spec.text or "").strip() or None)
    return TimerDef(None, None)


def select_process_id(xml: str) -> str:
    """Pick the ``<process>`` id to parse/execute from raw BPMN: prefer an executable process
    (``isExecutable="true"``), else the first ``<process>`` with an id. Shared by the onboarding
    wizard and any other auto-detection so selection is identical everywhere (ADR-027). Raises
    ``ET.ParseError`` on unparseable XML; returns "" when there is no ``<process>``."""
    root = ET.fromstring(xml)
    best = ""
    for el in root.iter():
        if local_name(el.tag) == "process":
            pid = el.get("id") or ""
            if el.get("isExecutable") == "true" and pid:
                return pid
            best = best or pid
    return best


def parse(
    xml: str, expected_process_id: str, *, profile: str = "common_subset"
) -> Tuple[Optional[BpmnModel], List[Finding]]:
    """Parse + run structural checks.

    ``profile`` (ADR-027 Phase 2) tunes only the executability *tier* of elements the parser
    already recognizes — under ``"parallel"`` a ``parallelGateway`` classifies ``executable``
    rather than ``documented`` for the coverage report. It does not change the parsed topology
    (the compiler + ``compilability_findings`` gate what actually runs).

    Returns ``(model, findings)``. ``model`` is ``None`` on a hard failure
    (unparseable XML or missing process). ``findings`` is a list of error-level
    ``Finding`` objects using stable codes shared with the registry.
    """
    findings: List[Finding] = []
    profile = normalize_profile(profile)  # ADR-034: retired granular values → common_executable

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        findings.append(Finding("bpmn_parse_error", f"XML did not parse: {exc}"))
        return None, findings

    processes = [e for e in root.iter() if local_name(e.tag) == "process"]
    match = next((p for p in processes if p.get("id") == expected_process_id), None)
    if match is None:
        findings.append(Finding(
            "bpmn_process_not_found",
            f"no bpmn:process with id '{expected_process_id}' "
            f"(found: {[p.get('id') for p in processes]})",
        ))
        return None, findings

    model = BpmnModel(process_id=expected_process_id)
    # ADR-027 Phase 2.2: boundary timers are wired post-loop (once their outgoing flow is known).
    # raw: boundary id -> (attached_to, cancel_activity, TimerDef).
    boundary_raw: Dict[str, Tuple[Optional[str], bool, TimerDef]] = {}
    # ADR-030 Phase 2.3: error boundaries, likewise wired post-loop.
    # raw: boundary id -> (attached_to, errorRef | _CATCH_ALL).
    error_boundary_raw: Dict[str, Tuple[Optional[str], object]] = {}
    # ADR-042 (Item F): event sub-processes (triggeredByEvent) — built post-loop once their body
    # start/ends are known. raw: esp id -> (enclosing scope id, the ESP container element for trigger).
    esp_raw: Dict[str, Tuple[str, Any]] = {}
    # ADR-043 (Item G): compensation. Collected during the walk, paired post-loop.
    associations: List[Tuple[Optional[str], Optional[str]]] = []   # (sourceRef, targetRef)
    comp_boundary_raw: Dict[str, Optional[str]] = {}               # comp boundary id -> attachedToRef (primary)
    comp_throw_raw: Dict[str, Tuple[bool, Optional[str]]] = {}     # throw id -> (is_end, activityRef)
    comp_handler_ids: Set[str] = set()                             # isForCompensation activity ids (off-flow)
    cancel_ends: List[str] = []                                    # endEvents carrying a cancelEventDefinition
    # ``<bpmn:error id=.. errorCode=..>`` definitions live at the definitions level (siblings of the
    # process), so scan the whole document: errorRef → the business error_code the boundary matches.
    error_defs: Dict[str, str] = {
        el.get("id"): (el.get("errorCode") or "")
        for el in root.iter() if local_name(el.tag) == "error" and el.get("id")
    }
    # ADR-031: <bpmn:message id=.. name=..> definitions (definitions level) → messageRef → name.
    message_defs: Dict[str, str] = {
        el.get("id"): (el.get("name") or "")
        for el in root.iter() if local_name(el.tag) == "message" and el.get("id")
    }

    def _msg_name(el) -> Optional[str]:
        ref = _message_ref(el)
        return message_defs.get(ref) or ref if ref else None

    # ADR-032 Phase 2.6: start/end are counted PER SCOPE (the top-level process needs exactly one
    # start; each embedded sub-process needs its own single start + ≥1 end). A nested start must NOT
    # inflate the top-level start count.
    scope_starts: Dict[str, List[str]] = {}
    scope_ends: Dict[str, List[str]] = {}

    def _record(node_id: str, scope_id: str) -> None:
        model.element_scope[node_id] = scope_id
        if scope_id in model.subprocesses:
            model.subprocesses[scope_id].member_ids.append(node_id)

    def walk(container, scope_id: str) -> None:
        """Process the flow nodes + sequence flows of one scope (process or subProcess), recursing
        into embedded sub-processes. Element ids are globally unique in BPMN, so flattening the nested
        scopes into the shared model collections never collides."""
        for child in list(container):
            name = local_name(child.tag)
            if name in IGNORE_CHILDREN:
                continue
            node_id = child.get("id")
            if name == "sequenceFlow":
                src, tgt = child.get("sourceRef"), child.get("targetRef")
                cond_el = next((gc for gc in child if local_name(gc.tag) == "conditionExpression"), None)
                has_cond = cond_el is not None
                cond_text = (cond_el.text or "").strip() if cond_el is not None else None
                model.flows.append(Flow(
                    id=node_id, source=src, target=tgt, has_condition=has_cond,
                    condition_expr=cond_text, name=child.get("name"),
                ))
                continue
            if name == "association":
                # ADR-043: an association links a compensation boundary → its handler activity (it is
                # NOT a sequence flow). Collect it; the compensation pairing is resolved post-loop.
                associations.append((child.get("sourceRef"), child.get("targetRef")))
                model.elements.append(ClassifiedElement(id=node_id, kind=name, tier="documented"))
                continue
            if name == "subProcess":
                if child.get("triggeredByEvent") == "true":
                    # ADR-042 (Item F): an EVENT sub-process is a scope-wide event handler, NOT a
                    # flattened box — it sits on no sequence flow (no parent-level in/out), so it is
                    # deliberately NOT added to node_ids. Record it raw (enclosing scope + container
                    # for trigger extraction) and recurse to parse the body; the trigger detection +
                    # handler registration happen post-loop.
                    esp_raw[node_id] = (scope_id, child)
                    _record(node_id, scope_id)
                    tier = "executable" if profile == "common_executable" else "documented"
                    model.elements.append(ClassifiedElement(id=node_id, kind=name, tier=tier))
                    walk(child, node_id)
                    continue
                # An embedded sub-process container: structural, not a task. Record + recurse.
                model.node_ids.add(node_id)
                model.subprocesses[node_id] = SubProcess(
                    id=node_id, name=child.get("name"), parent_scope=scope_id)
                # ADR-036: MI on a sub-process is a deferred stretch — capture it so the compilability
                # gate refuses it (bpmn_multi_instance_subprocess_unsupported), don't build it here.
                mi_sub = _multi_instance(child, node_id, on_subprocess=True)
                if mi_sub is not None:
                    model.multi_instance[node_id] = mi_sub
                _record(node_id, scope_id)
                tier = "executable" if profile == "common_executable" else "documented"
                model.elements.append(ClassifiedElement(id=node_id, kind=name, tier=tier))
                walk(child, node_id)
                continue
            if name == "callActivity":
                # ADR-039: cross-pack composition. Capture the callee target (calledElement = pack_key)
                # + version range (amendia:calledVersion, else the policy default). The compiler
                # inline-splices the pinned callee; compilability gates it (profile + structural).
                model.node_ids.add(node_id)
                target = child.get("calledElement") or _local_attr(child, "calledElement")
                vrange = _local_attr(child, "calledVersion") or DEFAULT_CALL_VERSION_RANGE
                has_mi = any(local_name(c.tag) == "multiInstanceLoopCharacteristics" for c in child)
                model.call_activities[node_id] = CallActivity(
                    id=node_id, target_pack=(target or None), version_range=vrange,
                    parent_scope=scope_id, is_multi_instance=has_mi)
                _record(node_id, scope_id)
                tier = "executable" if profile == "common_executable" else "documented"
                model.elements.append(ClassifiedElement(id=node_id, kind=name, tier=tier))
                continue
            _record(node_id, scope_id)
            _walk_node(child, name, node_id, scope_id, scope_starts, scope_ends,
                       boundary_raw, error_boundary_raw, _msg_name, model, findings, profile)

    def _walk_node(child, name, node_id, scope_id, scope_starts, scope_ends,
                   boundary_raw, error_boundary_raw, _msg_name, model, findings, profile):
        if name in NODE_KINDS:
            model.node_ids.add(node_id)
            has_mi = False
            if name in TASK_KINDS:
                model.tasks[node_id] = name
                if name == "businessRuleTask":  # advisory decisionRef (inference only — no DMN eval)
                    ref = child.get("calledDecision") or child.get("decisionRef")
                    if ref:
                        model.decision_refs[node_id] = ref
                elif name == "scriptTask" and any(local_name(c.tag) == "script" for c in child):
                    model.inline_scripts.append(node_id)  # inline body NOT executed (refused)
                # ADR-036: a multi-instance task runs N times — executable only under common_executable.
                mi = _multi_instance(child, node_id, on_subprocess=False)
                if mi is not None:
                    model.multi_instance[node_id] = mi
                    has_mi = True
                # ADR-043 (Item G): a compensation handler activity is OFF the sequence flow (invoked only
                # when its primary is compensated). Keep it a bound task, but track it so reachability +
                # the single-outgoing arity check skip it (like an event sub-process body).
                if child.get("isForCompensation") == "true":
                    comp_handler_ids.add(node_id)
            elif name == "exclusiveGateway":
                model.exclusive_gateways.append(node_id)
                if child.get("default"):
                    model.gateway_defaults[node_id] = child.get("default")
            elif name == "parallelGateway":
                model.parallel_gateways.append(node_id)
            elif name == "startEvent":
                scope_starts.setdefault(scope_id, []).append(node_id)
                if scope_id != model.process_id:
                    model.nested_starts.add(node_id)
            elif name == "endEvent":
                scope_ends.setdefault(scope_id, []).append(node_id)
                if scope_id != model.process_id:
                    model.nested_ends.add(node_id)
                # ADR-043: an endEvent carrying a compensateEventDefinition is a TERMINAL compensate
                # throw — compensate the scope, then end. A cancelEventDefinition (transaction cancel) is
                # the deferred auto-compensation trigger; record it so the gate can refuse.
                ced = _compensate_def(child)
                if ced is not None:
                    comp_throw_raw[node_id] = (True, ced.get("activityRef"))
                if _has_cancel_def(child):
                    cancel_ends.append(node_id)
            # Retain for coverage (ADR-027). A NODE_KIND is executable under common_subset unless it is
            # promoted by a profile: parallelGateway under "parallel" (Phase 2.1); the extended task
            # kinds (sendTask/scriptTask/manualTask/businessRuleTask) under "tasks" (Phase 2.7).
            executable = (name in EXECUTABLE_KINDS
                          or (profile == "common_executable" and name == "parallelGateway")
                          or (profile == "common_executable" and name in EXTENDED_TASK_KINDS))
            # ADR-036: a multi-instance task is executable only under common_executable, even though the
            # base task kind (serviceTask/userTask) is otherwise common-subset executable.
            if has_mi:
                executable = (profile == "common_executable")
            tier = "executable" if executable else "documented"
            model.elements.append(ClassifiedElement(id=node_id, kind=name, tier=tier))
        elif name == "intermediateCatchEvent" and _timer_def(child) is not None:
            # Timer intermediate catch — an execution construct under the "timers" profile (Phase 2.2):
            # the instance parks for the duration then auto-proceeds. Captured regardless of profile
            # (like parallel_gateways); the profile only decides the coverage tier + activation gate.
            td = _timer_def(child)
            model.node_ids.add(node_id)
            model.timer_catch_events[node_id] = td
            tier = "executable" if profile == "common_executable" else "documented"
            model.elements.append(ClassifiedElement(id=node_id, kind=name, tier=tier))
        elif name == "boundaryEvent" and _timer_def(child) is not None:
            # Timer boundary — wired post-loop (needs its outgoing flow). Only a wired boundary
            # (schedule + escalation target) becomes an execution construct; otherwise documented.
            boundary_raw[node_id] = (
                child.get("attachedToRef"), child.get("cancelActivity") != "false", _timer_def(child),
            )
        elif name == "boundaryEvent" and _error_ref(child) is not None:
            # Error boundary (Phase 2.3) — wired post-loop. A modeled business error on the host task
            # routes here instead of failing the instance. errorRef → error_code via the <bpmn:error>
            # defs (or _CATCH_ALL for no errorRef).
            error_boundary_raw[node_id] = (child.get("attachedToRef"), _error_ref(child))
        elif name == "boundaryEvent" and _compensate_def(child) is not None:
            # ADR-043 (Item G): a compensation boundary — attachedToRef is the compensable primary; the
            # handler is linked by an <association> (resolved post-loop). It has NO outgoing sequence
            # flow, so nothing to pull from model.flows.
            comp_boundary_raw[node_id] = child.get("attachedToRef")
            tier = "executable" if profile == "common_executable" else "documented"
            model.elements.append(ClassifiedElement(id=node_id, kind=name, tier=tier))
        elif name == "intermediateThrowEvent" and _compensate_def(child) is not None:
            # ADR-043: an intermediate compensate throw — compensate the enclosing scope's completed
            # compensable activities in reverse order, then continue via its single outgoing flow.
            ced = _compensate_def(child)
            model.node_ids.add(node_id)
            comp_throw_raw[node_id] = (False, ced.get("activityRef"))
            tier = "executable" if profile == "common_executable" else "documented"
            model.elements.append(ClassifiedElement(id=node_id, kind=name, tier=tier))
        elif name == "intermediateCatchEvent" and _has_message_def(child):
            # Message intermediate catch (Phase 2.4): parks WAITING_MESSAGE until a correlated inbound
            # message is delivered. Bindable (needs a manifest message binding for its message_name).
            model.node_ids.add(node_id)
            model.message_catch_events[node_id] = _msg_name(child)
            tier = "executable" if profile == "common_executable" else "documented"
            model.elements.append(ClassifiedElement(id=node_id, kind=name, tier=tier))
        elif name == "receiveTask":
            # Receive task (Phase 2.4): same as a message catch, modeled as a task.
            model.node_ids.add(node_id)
            model.receive_tasks[node_id] = _msg_name(child)
            tier = "executable" if profile == "common_executable" else "documented"
            model.elements.append(ClassifiedElement(id=node_id, kind=name, tier=tier))
        elif name == "eventBasedGateway":
            # Event-based gateway (Phase 2.4 capstone): waits for the FIRST of its arm catch events
            # (timer and/or message). Arms are its outgoing flow targets (resolved post-loop).
            model.node_ids.add(node_id)
            model.event_based_gateways[node_id] = []  # arms filled in after flows are known
            tier = "executable" if profile == "common_executable" else "documented"
            model.elements.append(ClassifiedElement(id=node_id, kind=name, tier=tier))
        elif name in RECOGNIZED_NON_EXECUTABLE:
            # Classify, don't reject: recognized standard BPMN outside the executable set.
            model.elements.append(ClassifiedElement(id=node_id, kind=name, tier="documented"))
            findings.append(Finding(
                "bpmn_documented_element",
                f"'{name}' is recognized BPMN but not executable today; documented only"
                + (f" (id={node_id})" if node_id else ""),
                element_id=node_id, severity="warning",
            ))
        else:
            # Not a recognized BPMN element at all (typos, vendor extensions).
            model.elements.append(ClassifiedElement(id=node_id, kind=name, tier="unknown"))
            findings.append(Finding(
                "bpmn_unknown_element",
                f"unrecognized BPMN element '{name}'" + (f" (id={node_id})" if node_id else ""),
                element_id=node_id, severity="info",
            ))

    # Walk the whole diagram (top-level process, recursing into embedded sub-processes).
    walk(match, expected_process_id)
    model.start_events = list(scope_starts.get(expected_process_id, []))
    model.end_events = list(scope_ends.get(expected_process_id, []))
    # Per-scope start/end for sub-processes; also fill each sub's start_id/end_ids + incoming/outgoing.
    for sub in model.subprocesses.values():
        sub_starts = scope_starts.get(sub.id, [])
        sub.start_id = sub_starts[0] if sub_starts else None
        sub.end_ids = list(scope_ends.get(sub.id, []))
        inc = next((f for f in model.flows if f.target == sub.id), None)
        out = next((f for f in model.flows if f.source == sub.id), None)
        sub.incoming_flow = inc.id if inc else None
        sub.outgoing_flow = out.id if out else None

    # ADR-027 Phase 2.2: wire timer boundary events. A boundary's outgoing sequenceFlow is NOT a
    # normal edge (its source is the attached-event, not a task) — pull it out of model.flows so the
    # task-arity/edge logic never sees it, and record the boundary→escalation target. Reachability is
    # augmented below (host → target) so an escalation node reached only via the boundary is not a
    # false "unreachable". A boundary with no outgoing flow or an empty timer stays documented.
    for bid, (attached_to, cancel, td) in boundary_raw.items():
        out_flow = next((f for f in model.flows if f.source == bid), None)
        if out_flow is not None:
            model.flows = [f for f in model.flows if f is not out_flow]  # not a normal edge
        target = out_flow.target if out_flow is not None else None
        if attached_to in model.call_activities:  # ADR-039: callActivity boundary still deferred
            model.subprocess_boundaries.append(bid)
            model.elements.append(ClassifiedElement(id=bid, kind="boundaryEvent", tier="documented"))
            continue
        wired = target is not None and attached_to is not None and timer_is_supported(td)
        if wired:
            model.boundary_timers[attached_to] = BoundaryTimer(
                id=bid, attached_to=attached_to, timer=td, cancel_activity=cancel, target=target,
            )
            tier = "executable" if profile == "common_executable" else "documented"
            model.elements.append(ClassifiedElement(id=bid, kind="boundaryEvent", tier=tier))
        else:
            # Documented-only boundary (off the live path / unsupported timer): classify + warn,
            # matching the RECOGNIZED_NON_EXECUTABLE path so existing behavior is preserved.
            model.elements.append(ClassifiedElement(id=bid, kind="boundaryEvent", tier="documented"))
            findings.append(Finding(
                "bpmn_documented_element",
                f"'boundaryEvent' is recognized BPMN but not executable today; documented only (id={bid})",
                element_id=bid, severity="warning",
            ))

    # ADR-030 Phase 2.3: wire error boundary events (same shape as timer boundaries). error_code is
    # the <bpmn:error errorCode> the boundary's errorRef points at; a catch-all (_CATCH_ALL) → None.
    for bid, (attached_to, ref) in error_boundary_raw.items():
        out_flow = next((f for f in model.flows if f.source == bid), None)
        if out_flow is not None:
            model.flows = [f for f in model.flows if f is not out_flow]
        target = out_flow.target if out_flow is not None else None
        if attached_to in model.call_activities:  # ADR-039: callActivity boundary still deferred
            model.subprocess_boundaries.append(bid)
            model.elements.append(ClassifiedElement(id=bid, kind="boundaryEvent", tier="documented"))
            continue
        wired = target is not None and attached_to is not None
        if wired:
            code = None if ref is _CATCH_ALL else (error_defs.get(ref) or str(ref))
            model.error_boundaries.setdefault(attached_to, []).append(
                ErrorBoundary(id=bid, attached_to=attached_to, error_code=code, target=target)
            )
            tier = "executable" if profile == "common_executable" else "documented"
            model.elements.append(ClassifiedElement(id=bid, kind="boundaryEvent", tier=tier))
        else:
            model.elements.append(ClassifiedElement(id=bid, kind="boundaryEvent", tier="documented"))
            findings.append(Finding(
                "bpmn_documented_element",
                f"'boundaryEvent' is recognized BPMN but not executable today; documented only (id={bid})",
                element_id=bid, severity="warning",
            ))

    # ADR-042 (Item F): build each event sub-process. A triggeredByEvent subProcess is a scope-wide
    # handler whose START event's trigger fires it from anywhere in enclosing_scope; the body is the
    # inlined handler. Only an INTERRUPTING error/timer start runs — we register its handler onto the
    # enclosing scope's boundary map so the compiler reuses ADR-041's scope router (generalized to a
    # process-level scope). A message/signal/escalation or non-interrupting start is recorded
    # unsupported for the compilability gate to refuse.
    for esp_id, (enc, esp_el) in esp_raw.items():
        start_el = next((c for c in esp_el if local_name(c.tag) == "startEvent"), None)
        start_id = (scope_starts.get(esp_id) or [None])[0]
        ends = list(scope_ends.get(esp_id, []))
        body_succ = next(
            (f.target for f in model.flows if start_id is not None and f.source == start_id), None)
        is_interrupting = start_el is None or start_el.get("isInterrupting") != "false"
        err = _error_ref(start_el) if start_el is not None else None
        td = _timer_def(start_el) if start_el is not None else None
        esp = EventSubProcess(
            id=esp_id, enclosing_scope=enc, is_interrupting=is_interrupting,
            start_id=start_id, body_start_successor=body_succ, end_ids=ends,
        )
        if not is_interrupting:
            esp.unsupported = ("non-interrupting event sub-process (a concurrent handler) is not "
                               "supported — interrupting error/timer start only")
        elif err is not None:
            esp.trigger = "error"
            esp.error_code = None if err is _CATCH_ALL else (error_defs.get(err) or str(err))
        elif td is not None and timer_is_supported(td):
            esp.trigger = "timer"
            esp.timer = td
        else:
            esp.unsupported = ("event sub-process start must be an interrupting error or timer "
                               "trigger (message/signal/escalation start deferred)")
        model.event_subprocesses[esp_id] = esp
        # Register the runnable handler onto its enclosing scope, reusing ADR-041's boundary router:
        # an error ESP is a scope-wide error fallback, a timer ESP a scope-wide SLA. The handler entry
        # is the body's start-successor (the trigger start itself is plumbing, never a graph node).
        if esp.unsupported is None and body_succ is not None:
            if esp.trigger == "error":
                model.error_boundaries.setdefault(enc, []).append(
                    ErrorBoundary(id=esp_id, attached_to=enc, error_code=esp.error_code, target=body_succ))
            else:  # timer
                model.boundary_timers[enc] = BoundaryTimer(
                    id=esp_id, attached_to=enc, timer=td, cancel_activity=True, target=body_succ)

    # ADR-043 (Item G): resolve compensation pairings. Each compensate boundary (attachedTo = the
    # compensable primary) links to its handler activity through an <association> (source = boundary id,
    # target = the isForCompensation handler). Build the handler pairing + the primary→handler inverse.
    assoc_by_source: Dict[str, List[str]] = {}
    for src, tgt in associations:
        if src and tgt:
            assoc_by_source.setdefault(src, []).append(tgt)
    for bid, primary in comp_boundary_raw.items():
        handler = next((t for t in assoc_by_source.get(bid, []) if t in comp_handler_ids), None)
        if handler is None or primary is None or primary not in model.tasks:
            findings.append(Finding(
                "bpmn_compensation_boundary_unwired",
                f"compensation boundary '{bid}' must attach to a task and associate to an "
                f"isForCompensation handler activity (attachedTo='{primary}')",
                element_id=bid))
            continue
        model.compensation_handlers[handler] = CompensationHandler(
            handler_id=handler, primary_id=primary, boundary_id=bid)
        model.compensations[primary] = handler
    # Compensate throw events → their enclosing scope (whose completed compensable activities they undo).
    for tid, (is_end, aref) in comp_throw_raw.items():
        model.compensate_throws[tid] = CompensateThrow(
            id=tid, scope=model.element_scope.get(tid, model.process_id), is_end=is_end, activity_ref=aref)
    model.cancel_end_events = list(cancel_ends)  # read by compilability for the transaction-cancel refusal

    # ADR-031: an event-based gateway's arms are its outgoing flow targets (each an arm catch event).
    for gw in model.event_based_gateways:
        model.event_based_gateways[gw] = [f.target for f in model.outgoing(gw)]

    # ADR-033 Phase 2.7: a FULLY-ISOLATED extended-task-kind (no incoming/outgoing flow) is decorative
    # documentation, not an executable node — reclassify it (mirrors wired-vs-documented for boundary
    # events) so a floating sendTask/businessRuleTask attaches without a false unreachable-node error.
    # A connected one stays an executable task node (reachability then validates it normally).
    _flow_ends = {f.source for f in model.flows} | {f.target for f in model.flows}
    for tid in [t for t, k in model.tasks.items() if k in EXTENDED_TASK_KINDS and t not in _flow_ends]:
        del model.tasks[tid]
        model.node_ids.discard(tid)
        model.decision_refs.pop(tid, None)
        if tid in model.inline_scripts:
            model.inline_scripts.remove(tid)
        for e in model.elements:
            if e.id == tid:
                e.tier = "documented"

    # dangling flow refs
    for fl in model.flows:
        if fl.source not in model.node_ids:
            findings.append(Finding(
                "bpmn_dangling_flow",
                f"sequenceFlow '{fl.id}' sourceRef '{fl.source}' is not a known node",
                element_id=fl.id,
            ))
        if fl.target not in model.node_ids:
            findings.append(Finding(
                "bpmn_dangling_flow",
                f"sequenceFlow '{fl.id}' targetRef '{fl.target}' is not a known node",
                element_id=fl.id,
            ))

    # exactly one TOP-LEVEL start, at least one top-level end (scoped — nested starts don't count).
    if len(model.start_events) != 1:
        findings.append(Finding(
            "bpmn_start_event_count",
            f"expected exactly one startEvent, found {len(model.start_events)}",
        ))
    if not model.end_events:
        findings.append(Finding("bpmn_no_end_event", "no endEvent found"))

    # ADR-032 Phase 2.6: each embedded sub-process needs its own single start + ≥1 end, and (simple
    # case) exactly one incoming + one outgoing at the parent level.
    for sub in model.subprocesses.values():
        n_start = len(scope_starts.get(sub.id, []))
        if n_start != 1:
            findings.append(Finding("bpmn_subprocess_start_count",
                                    f"sub-process '{sub.id}' must have exactly one start event, found {n_start}",
                                    element_id=sub.id))
        if not sub.end_ids:
            findings.append(Finding("bpmn_subprocess_no_end",
                                    f"sub-process '{sub.id}' has no end event", element_id=sub.id))
        n_in = sum(1 for f in model.flows if f.target == sub.id)
        n_out = sum(1 for f in model.flows if f.source == sub.id)
        if n_in != 1 or n_out != 1:
            findings.append(Finding("bpmn_subprocess_arity",
                                    f"sub-process '{sub.id}' must have exactly one incoming and one outgoing "
                                    f"flow at the parent level, found {n_in} in / {n_out} out",
                                    element_id=sub.id))

    # reachability (forward from start, backward to any end) — on the FLATTENED graph: entering a
    # sub-process box runs its start, and each internal end continues after the box (2.6.c inline).
    adj: Dict[str, List[str]] = {n: [] for n in model.node_ids}
    radj: Dict[str, List[str]] = {n: [] for n in model.node_ids}
    for fl in model.flows:
        if fl.source in adj and fl.target in adj:
            adj[fl.source].append(fl.target)
            radj[fl.target].append(fl.source)
    for sub in model.subprocesses.values():
        out_target = next((f.target for f in model.flows if f.source == sub.id), None)
        if sub.start_id and sub.id in adj:            # box → its internal start
            adj[sub.id].append(sub.start_id)
            radj[sub.start_id].append(sub.id)
        for eid in sub.end_ids:                        # internal end → continue after the box
            if out_target and eid in adj and out_target in adj:
                adj[eid].append(out_target)
                radj[out_target].append(eid)
    # ADR-027 Phase 2.2: a timer boundary lets its host reach the escalation target — model that as
    # a host→target reachability edge so an escalation node reached only via the boundary is not a
    # false "unreachable from start" (the boundary flow itself was removed from model.flows above).
    for host, bt in model.boundary_timers.items():
        if host in adj and bt.target in adj:
            adj[host].append(bt.target)
            radj[bt.target].append(host)
    # ADR-030 Phase 2.3: same for error boundaries — the host can reach each error target.
    for host, ebs in model.error_boundaries.items():
        for eb in ebs:
            if host in adj and eb.target in adj:
                adj[host].append(eb.target)
                radj[eb.target].append(host)
    # ADR-042 (Item F): an event sub-process's body is reached when its trigger fires anywhere in the
    # enclosing scope — model that as (enclosing-scope entry) → the ESP trigger start (then start →
    # body via the body's own internal flow). The enclosing-scope "entry" is the enclosing subProcess
    # box, or the process start for a process-level ESP. The body's ends are TERMINAL (they end the
    # instance), so seed the backward reachability from them below.
    # Augment for every ESP (even an unsupported one) so its body never trips a generic reachability
    # error — an unsupported ESP is refused cleanly by the compilability gate with its specific code.
    esp_end_ids: Set[str] = set()
    for esp in model.event_subprocesses.values():
        if not esp.start_id:
            continue
        src = esp.enclosing_scope if esp.enclosing_scope in adj else (
            model.start_events[0] if model.start_events else None)
        if src is not None and esp.start_id in adj:
            adj[src].append(esp.start_id)
            radj[esp.start_id].append(src)
        esp_end_ids.update(e for e in esp.end_ids if e in radj)

    # ADR-043 (Item G): compensation handler activities are OFF the sequence flow (invoked only by a
    # compensate throw, never reached from start / never continuing to an end) — exclude them from the
    # reachability checks, exactly like an event sub-process body handler.
    off_flow = set(model.compensation_handlers)

    if model.start_events:
        reachable = _bfs(adj, model.start_events[0])
        for n in sorted(model.node_ids - reachable - off_flow):
            findings.append(Finding(
                "bpmn_unreachable_node",
                f"node '{n}' is not reachable from the start event",
                element_id=n,
            ))
    if model.end_events or esp_end_ids:
        can_reach_end: Set[str] = set()
        for e in list(model.end_events) + list(esp_end_ids):  # ADR-042: ESP body ends are terminal
            can_reach_end |= _bfs(radj, e)
        for n in sorted(model.node_ids - can_reach_end - off_flow):
            findings.append(Finding(
                "bpmn_no_path_to_end",
                f"node '{n}' cannot reach an end event",
                element_id=n,
            ))

    # exclusive gateway conditions
    for gw in model.exclusive_gateways:
        default_flow = model.gateway_defaults.get(gw)
        conds: List[str] = []
        for fl in model.outgoing(gw):
            if fl.has_condition:
                conds.append(fl.id)
            elif fl.id != default_flow:
                findings.append(Finding(
                    "bpmn_conditionless_exclusive_flow",
                    f"exclusiveGateway '{gw}' outgoing flow '{fl.id}' has no "
                    f"condition and is not the default",
                    element_id=fl.id,
                ))
        model.exclusive_conditions[gw] = conds

    # parallel gateway forks must be unconditional
    for gw in model.parallel_gateways:
        for fl in model.outgoing(gw):
            if fl.has_condition:
                findings.append(Finding(
                    "bpmn_parallel_flow_condition",
                    f"parallelGateway '{gw}' outgoing flow '{fl.id}' must not "
                    f"carry a condition",
                    element_id=fl.id,
                ))

    return model, findings


def _bfs(adj: Dict[str, List[str]], start: str) -> Set[str]:
    seen: Set[str] = set()
    stack = [start]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(adj.get(n, []))
    return seen
