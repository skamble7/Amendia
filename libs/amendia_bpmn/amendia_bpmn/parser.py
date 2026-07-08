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

from typing import Dict, List, Optional, Set, Tuple
from xml.etree import ElementTree as ET

from amendia_bpmn.model import (
    IGNORE_CHILDREN,
    NODE_KINDS,
    TASK_KINDS,
    BpmnModel,
    Finding,
    Flow,
    local_name,
)


def parse(xml: str, expected_process_id: str) -> Tuple[Optional[BpmnModel], List[Finding]]:
    """Parse + run structural checks.

    Returns ``(model, findings)``. ``model`` is ``None`` on a hard failure
    (unparseable XML or missing process). ``findings`` is a list of error-level
    ``Finding`` objects using stable codes shared with the registry.
    """
    findings: List[Finding] = []

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

    for child in list(match):
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
        if name in NODE_KINDS:
            model.node_ids.add(node_id)
            if name in TASK_KINDS:
                model.tasks[node_id] = name
            elif name == "exclusiveGateway":
                model.exclusive_gateways.append(node_id)
                if child.get("default"):
                    model.gateway_defaults[node_id] = child.get("default")
            elif name == "parallelGateway":
                model.parallel_gateways.append(node_id)
            elif name == "startEvent":
                model.start_events.append(node_id)
            elif name == "endEvent":
                model.end_events.append(node_id)
        else:
            findings.append(Finding(
                "bpmn_unsupported_element",
                f"unsupported BPMN element '{name}'" + (f" (id={node_id})" if node_id else ""),
                element_id=node_id,
            ))

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

    # exactly one start, at least one end
    if len(model.start_events) != 1:
        findings.append(Finding(
            "bpmn_start_event_count",
            f"expected exactly one startEvent, found {len(model.start_events)}",
        ))
    if not model.end_events:
        findings.append(Finding("bpmn_no_end_event", "no endEvent found"))

    # reachability (forward from start, backward to any end)
    adj: Dict[str, List[str]] = {n: [] for n in model.node_ids}
    radj: Dict[str, List[str]] = {n: [] for n in model.node_ids}
    for fl in model.flows:
        if fl.source in adj and fl.target in adj:
            adj[fl.source].append(fl.target)
            radj[fl.target].append(fl.source)

    if model.start_events:
        reachable = _bfs(adj, model.start_events[0])
        for n in sorted(model.node_ids - reachable):
            findings.append(Finding(
                "bpmn_unreachable_node",
                f"node '{n}' is not reachable from the start event",
                element_id=n,
            ))
    if model.end_events:
        can_reach_end: Set[str] = set()
        for e in model.end_events:
            can_reach_end |= _bfs(radj, e)
        for n in sorted(model.node_ids - can_reach_end):
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
