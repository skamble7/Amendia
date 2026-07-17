# amendia_bpmn/semantics.py
"""Inference-oriented BPMN extraction (ADR-027 Phase 1).

A SECOND, separate pass over the whole ``<definitions>`` — deliberately independent of the lean
executable ``parse()`` (which feeds the compiler + registry Stage 1). This reads the full diagram
for *understanding*: lanes, pools/message-flows, every flow-node subtype, event-definition
subtypes, boundary attachments, sequence-flow conditions, DMN linkage, and data objects. It is a
**read-only input to inference** — nothing here executes. All fields are best-effort; missing
structure is tolerated (empty lists / ``None``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

from amendia_bpmn.model import local_name

TASK_KINDS = {
    "serviceTask", "userTask", "sendTask", "receiveTask", "manualTask",
    "scriptTask", "businessRuleTask", "task",
}
SUBPROCESS_KINDS = {"callActivity", "subProcess", "adHocSubProcess", "transaction"}
GATEWAY_KINDS = {"exclusiveGateway", "parallelGateway", "inclusiveGateway", "complexGateway", "eventBasedGateway"}
EVENT_KINDS = {"startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent", "boundaryEvent"}
FLOW_NODE_KINDS = TASK_KINDS | SUBPROCESS_KINDS | GATEWAY_KINDS | EVENT_KINDS

_EVENT_DEFINITIONS = {
    "messageEventDefinition": "message",
    "timerEventDefinition": "timer",
    "errorEventDefinition": "error",
    "signalEventDefinition": "signal",
    "escalationEventDefinition": "escalation",
    "conditionalEventDefinition": "conditional",
    "linkEventDefinition": "link",
    "terminateEventDefinition": "terminate",
}


@dataclass
class SemLane:
    id: str
    name: Optional[str]
    member_ids: List[str] = field(default_factory=list)
    parent: Optional[str] = None  # parent lane id (nested lanes)


@dataclass
class SemPool:
    id: str
    name: Optional[str]
    process_ref: Optional[str]
    is_external: bool  # a pool whose processRef is NOT this process


@dataclass
class SemMessageFlow:
    id: str
    name: Optional[str]
    source: Optional[str]
    target: Optional[str]


@dataclass
class SemFlowNode:
    id: str
    name: Optional[str]
    kind: str                      # BPMN local-name
    lane_id: Optional[str] = None
    documentation: Optional[str] = None
    event_subtype: Optional[str] = None       # message | timer | error | signal | ...
    attached_to: Optional[str] = None         # boundaryEvent → host activity id
    cancel_activity: Optional[bool] = None     # boundaryEvent interrupting?
    decision_ref: Optional[str] = None         # businessRuleTask → DMN decision id (best effort)


@dataclass
class SemSequenceFlow:
    id: str
    source: Optional[str]
    target: Optional[str]
    name: Optional[str] = None
    condition: Optional[str] = None            # raw conditionExpression text


@dataclass
class SemDataObject:
    id: str
    name: Optional[str]
    kind: str                      # dataObject | dataObjectReference | dataStoreReference | dataStore


@dataclass
class BpmnSemanticModel:
    process_id: str
    lanes: List[SemLane] = field(default_factory=list)
    pools: List[SemPool] = field(default_factory=list)
    message_flows: List[SemMessageFlow] = field(default_factory=list)
    flow_nodes: List[SemFlowNode] = field(default_factory=list)
    sequence_flows: List[SemSequenceFlow] = field(default_factory=list)
    data_objects: List[SemDataObject] = field(default_factory=list)

    def node(self, node_id: str) -> Optional[SemFlowNode]:
        return next((n for n in self.flow_nodes if n.id == node_id), None)


def _children(el) -> List:
    return list(el)


def _doc_text(el) -> Optional[str]:
    for ch in el:
        if local_name(ch.tag) == "documentation" and (ch.text or "").strip():
            return ch.text.strip()
    return None


def _event_subtype(el) -> Optional[str]:
    for ch in el:
        sub = _EVENT_DEFINITIONS.get(local_name(ch.tag))
        if sub:
            return sub
    return None


def _decision_ref(el) -> Optional[str]:
    # camunda/zeebe/std variants: a calledDecision attr, or a *:decisionRef anywhere in the subtree.
    for k, v in el.attrib.items():
        if local_name(k) in ("calledDecision", "decisionRef", "decisionId") and v:
            return v
    for desc in el.iter():
        for k, v in desc.attrib.items():
            if local_name(k) in ("decisionRef", "decisionId", "calledDecision") and v:
                return v
    return None


def _collect_lanes(lane_set_el, parent: Optional[str], out: List[SemLane], member_of: Dict[str, str]) -> None:
    for lane in lane_set_el:
        if local_name(lane.tag) != "lane":
            continue
        lid = lane.get("id") or ""
        members: List[str] = []
        for ch in lane:
            lname = local_name(ch.tag)
            if lname == "flowNodeRef" and (ch.text or "").strip():
                ref = ch.text.strip()
                members.append(ref)
                member_of[ref] = lid
            elif lname == "childLaneSet":
                _collect_lanes(ch, lid, out, member_of)
        out.append(SemLane(id=lid, name=lane.get("name"), member_ids=members, parent=parent))


def extract_semantics(xml: str, process_id: str) -> BpmnSemanticModel:
    """Read the whole diagram into an inference-oriented model. Tolerant of missing structure."""
    model = BpmnSemanticModel(process_id=process_id)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return model

    # collaboration: pools + message flows
    for el in root.iter():
        ln = local_name(el.tag)
        if ln == "participant":
            pref = el.get("processRef")
            # A pool is "this process" only when its processRef matches; a black-box pool
            # (no processRef) or one referencing another process is external.
            model.pools.append(SemPool(
                id=el.get("id") or "", name=el.get("name"),
                process_ref=pref, is_external=(pref != process_id),
            ))
        elif ln == "messageFlow":
            model.message_flows.append(SemMessageFlow(
                id=el.get("id") or "", name=el.get("name"),
                source=el.get("sourceRef"), target=el.get("targetRef"),
            ))

    # the target process
    proc = next((p for p in root.iter() if local_name(p.tag) == "process" and p.get("id") == process_id), None)
    if proc is None:
        return model

    member_of: Dict[str, str] = {}
    for child in proc:
        if local_name(child.tag) == "laneSet":
            _collect_lanes(child, None, model.lanes, member_of)

    for child in proc:
        ln = local_name(child.tag)
        if ln == "sequenceFlow":
            cond = next((c.text for c in child if local_name(c.tag) == "conditionExpression"), None)
            model.sequence_flows.append(SemSequenceFlow(
                id=child.get("id") or "", source=child.get("sourceRef"), target=child.get("targetRef"),
                name=child.get("name"), condition=(cond or "").strip() or None,
            ))
        elif ln in ("dataObject", "dataObjectReference", "dataStoreReference", "dataStore"):
            model.data_objects.append(SemDataObject(id=child.get("id") or "", name=child.get("name"), kind=ln))
        elif ln in FLOW_NODE_KINDS:
            nid = child.get("id") or ""
            node = SemFlowNode(
                id=nid, name=child.get("name"), kind=ln, lane_id=member_of.get(nid),
                documentation=_doc_text(child),
            )
            if ln in EVENT_KINDS:
                node.event_subtype = _event_subtype(child)
            if ln == "boundaryEvent":
                node.attached_to = child.get("attachedToRef")
                node.cancel_activity = child.get("cancelActivity") != "false"
            if ln == "businessRuleTask":
                node.decision_ref = _decision_ref(child)
            model.flow_nodes.append(node)

    return model
