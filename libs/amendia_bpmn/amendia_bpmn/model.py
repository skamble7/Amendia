# amendia_bpmn/model.py
"""BPMN model dataclasses + the Iteration-1 element subset constants.

Shared between the process-registry (validation) and the agent-runtime (graph
compilation). The registry only needs presence of conditions; the runtime
compiler additionally needs the raw condition text and the start/end/default
topology — those extra fields are additive and ignored by the registry.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

TASK_KINDS = {"serviceTask", "userTask"}
GATEWAY_KINDS = {"exclusiveGateway", "parallelGateway"}
EVENT_KINDS = {"startEvent", "endEvent"}
NODE_KINDS = TASK_KINDS | GATEWAY_KINDS | EVENT_KINDS
IGNORE_CHILDREN = {"documentation", "extensionElements", "incoming", "outgoing"}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def compute_sha256(xml: str) -> str:
    return hashlib.sha256(xml.encode("utf-8")).hexdigest()


@dataclass
class Finding:
    """Neutral, framework-agnostic parse finding (severity is always error here)."""

    code: str
    message: str
    element_id: Optional[str] = None


@dataclass
class Flow:
    id: str
    source: str
    target: str
    has_condition: bool
    condition_expr: Optional[str] = None  # raw <conditionExpression> text (runtime compiler)
    name: Optional[str] = None


@dataclass
class BpmnModel:
    process_id: str
    tasks: Dict[str, str] = field(default_factory=dict)          # id -> serviceTask|userTask
    exclusive_gateways: List[str] = field(default_factory=list)
    parallel_gateways: List[str] = field(default_factory=list)
    node_ids: Set[str] = field(default_factory=set)
    flows: List[Flow] = field(default_factory=list)
    # exclusive gateway id -> list of outgoing flow ids that carry a condition (registry stages)
    exclusive_conditions: Dict[str, List[str]] = field(default_factory=dict)
    # runtime-compiler topology (additive; unused by the registry)
    start_events: List[str] = field(default_factory=list)
    end_events: List[str] = field(default_factory=list)
    gateway_defaults: Dict[str, str] = field(default_factory=dict)  # gateway id -> default flow id

    def outgoing(self, node_id: str) -> List[Flow]:
        return [f for f in self.flows if f.source == node_id]
