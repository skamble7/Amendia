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
from typing import Any, Dict, List, Optional, Set

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

# ADR-033 (Phase 2.7): the full standard BPMN task set is bindable → each routes to an existing
# executor category (no new engine). ``receiveTask`` is handled via the message path (Phase 2.4) so
# it is captured in ``receive_tasks``, NOT here (it is not a capability/human task node).
TASK_KINDS = {"serviceTask", "userTask", "sendTask", "scriptTask", "manualTask", "businessRuleTask"}
# The two original task kinds are executable under ``common_subset``; the rest are promoted to
# executable only under the ``tasks`` profile (Phase 2.7), like each prior construct rung.
COMMON_TASK_KINDS = {"serviceTask", "userTask"}
EXTENDED_TASK_KINDS = TASK_KINDS - COMMON_TASK_KINDS  # sendTask/scriptTask/manualTask/businessRuleTask
GATEWAY_KINDS = {"exclusiveGateway", "parallelGateway"}
EVENT_KINDS = {"startEvent", "endEvent"}
NODE_KINDS = TASK_KINDS | GATEWAY_KINDS | EVENT_KINDS
IGNORE_CHILDREN = {"documentation", "extensionElements", "incoming", "outgoing"}

# The runtime-executable node kinds (the subset ``compile_graph`` runs under ``common_subset``).
# The extended task kinds + ``parallelGateway`` are NODE_KINDS but classified ``documented`` until
# their profile promotes them (ADR-027 trap 1).
EXECUTABLE_KINDS = COMMON_TASK_KINDS | {"exclusiveGateway"} | EVENT_KINDS

# BPMN task kind → executor category (ADR-033). One shared map drives validation (bijection) and
# makes adding a task kind a one-line change; the compiler treats a task by its executor CATEGORY,
# not its BPMN tag. ``messageCatch`` is a binding element_kind (not a BPMN tag) included for the
# registry bijection alongside ``receiveTask``.
TASK_EXECUTOR_CATEGORY = {
    "serviceTask": "capability",
    "userTask": "human",
    "sendTask": "capability",       # the bound capability performs the send (side_effectful → gate)
    "scriptTask": "capability",     # a bound skill capability computes; inline <script> is NOT run
    "manualTask": "human",          # a human performs it offline (default hitl.mode = manual)
    "businessRuleTask": "capability",  # a bound decision capability; native DMN is deferred (ADR-033)
    "receiveTask": "message",       # Phase 2.4
    "messageCatch": "message",      # Phase 2.4 (binding element_kind, not a BPMN tag)
    "callActivity": "call",         # ADR-039 — binds a cross-pack `call` executor (inline-compiled)
}

# Recognized standard BPMN elements outside the executable set (ADR-027 tier ``documented``).
# Accepted + retained + surfaced as warnings; never a hard error.
RECOGNIZED_NON_EXECUTABLE = {
    "laneSet", "lane", "subProcess", "transaction", "adHocSubProcess", "callActivity",
    "receiveTask", "task",
    "eventBasedGateway", "inclusiveGateway", "complexGateway",
    "intermediateCatchEvent", "intermediateThrowEvent", "boundaryEvent",
    "dataObject", "dataObjectReference", "dataStoreReference", "dataStore",
    "textAnnotation", "association", "group", "ioSpecification",
}

# Classification tiers (ADR-027 §2).
ELEMENT_TIERS = ("executable", "documented", "unknown")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def compute_sha256(xml: str) -> str:
    return hashlib.sha256(xml.encode("utf-8")).hexdigest()


@dataclass
class Finding:
    """Neutral, framework-agnostic parse finding.

    ``severity`` is a plain string (``"error" | "warning" | "info"``) — the lib stays
    framework-free; the process-registry maps it onto its own ``Severity`` enum. Defaults to
    ``"error"`` so every existing construction stays an error unless explicitly demoted
    (ADR-027 reject→classify)."""

    code: str
    message: str
    element_id: Optional[str] = None
    severity: str = "error"


@dataclass
class ClassifiedElement:
    """One element the parser encountered, tagged by executability tier (ADR-027 §2).

    Retained for **every** element — executable, documented, or unknown — so the coverage
    report can surface what runs vs what is documentation-only. ``kind`` is the BPMN
    local-name; ``tier`` is one of :data:`ELEMENT_TIERS`."""

    id: Optional[str]
    kind: str
    tier: str


@dataclass
class Flow:
    id: str
    source: str
    target: str
    has_condition: bool
    condition_expr: Optional[str] = None  # raw <conditionExpression> text (runtime compiler)
    name: Optional[str] = None


@dataclass
class TimerDef:
    """A ``timerEventDefinition``'s schedule spec (ADR-027 Phase 2.2). ``kind`` is the sub-element
    that carried it: ``duration`` (ISO-8601 ``timeDuration`` e.g. ``PT4H``), ``date`` (absolute
    ISO-8601 ``timeDate``), or ``cycle`` (``timeCycle`` — recognized but unsupported this rung).
    ``value`` is the raw text (``None`` when the definition is present but empty, as in a
    documentation-only diagram)."""

    kind: Optional[str] = None       # duration | date | cycle | None
    value: Optional[str] = None      # raw ISO-8601 text


@dataclass
class BoundaryTimer:
    """An interrupting timer ``boundaryEvent`` attached to a host activity (ADR-027 Phase 2.2).

    Captured only when it is *wired* — has both a schedule and an outgoing sequence flow to an
    escalation target — so a documentation-only boundary event (no timer text, no outgoing) stays
    tier ``documented`` and never becomes an execution construct."""

    id: str                          # the boundaryEvent id
    attached_to: str                 # host activity id (the HITL gate it guards)
    timer: TimerDef
    cancel_activity: bool            # interrupting? (cancelActivity != "false")
    target: str                      # the boundary's outgoing flow target (escalation node)


@dataclass
class ErrorBoundary:
    """An error ``boundaryEvent`` attached to a host task (ADR-030 / Phase 2.3). Models a *business*
    error (payment rejected, screening hit) as a first-class routed branch — distinct from a
    technical failure. ``error_code`` is the ``<bpmn:error errorCode>`` its ``errorRef`` points at
    (``None`` = a catch-all boundary, no ``errorRef``). Captured only when wired (has an outgoing
    flow to a rework/return target); an unwired error boundary stays tier ``documented``."""

    id: str                          # the boundaryEvent id
    attached_to: str                 # host task id (the capability whose error it catches)
    error_code: Optional[str]        # matched against the raised code; None = catch-all
    target: str                      # the boundary's outgoing flow target (rework/return node)


@dataclass
class MultiInstance:
    """A ``multiInstanceLoopCharacteristics`` on a host activity (ADR-036 / Backlog #3). The activity
    runs N times — ``is_sequential`` chooses a guarded loop vs a parallel ``Send`` fan-out. N is bound
    by ``cardinality`` (``<loopCardinality>``) or the length of the ``collection_ref`` list artifact
    (``loopDataInputRef``); ``item_name`` (``inputDataItem``) is the per-iteration input variable the
    collection item is injected under. ``completion_condition`` (``completionCondition``) allows a
    sequential early-exit (evaluated after each iteration; ignored for parallel — early-cancel deferred).
    Each iteration's output is scoped by index and aggregated on join: ``aggregation="list"`` (default)
    collects a single list artifact under the binding name; ``"indexed"`` keeps ``{binding}#i`` keys.

    Captured for a *task* host (executable) and also a *subProcess* host (refused — deferred stretch),
    so the compilability gate can distinguish and reject the latter."""

    attached_to: str                 # host activity id
    is_sequential: bool = False
    cardinality: Optional[int] = None       # <loopCardinality> literal (bound on N)
    collection_ref: Optional[str] = None    # loopDataInputRef → the list artifact iterated
    item_name: Optional[str] = None         # inputDataItem → per-iteration input var name
    completion_condition: Optional[str] = None  # raw <completionCondition> text (sequential early-exit)
    aggregation: str = "list"               # "list" | "indexed" (amendia:aggregation ext attr; default list)
    on_subprocess: bool = False             # host is a subProcess (deferred — refused by compilability)


@dataclass
class SubProcess:
    """An embedded ``subProcess`` — a nested scope with its own start/end and internal flow (ADR-032
    / Phase 2.6). The compiler *inlines* (flattens) it into the parent graph, so everything already
    built works inside it. The container element itself is structural (not bound, not a node); its
    start/end become edges. Arbitrary nesting via ``parent_scope`` (the process id or a parent
    subProcess id)."""

    id: str
    name: Optional[str]
    parent_scope: str                # the containing scope: process_id or a parent subProcess id
    start_id: Optional[str] = None   # its single start event (validated)
    end_ids: List[str] = field(default_factory=list)     # its ≥1 end events
    member_ids: List[str] = field(default_factory=list)  # direct member node ids (incl nested subProcess ids)
    incoming_flow: Optional[str] = None  # parent-level flow id INTO the box (source → subProcess)
    outgoing_flow: Optional[str] = None  # parent-level flow id OUT of the box (subProcess → target)


@dataclass
class CallActivity:
    """A ``callActivity`` invoking **another pack** as a reusable sub-process (ADR-039). The compiler
    inline-compiles (splices) the pinned callee pack's graph in at this node — one instance, one
    checkpoint, one audit trail (mirrors the ADR-032 sub-process flatten, across packs). ``target_pack``
    is the callee's ``pack_key`` (``calledElement``); ``version_range`` is a semver range (Amendia
    extension ``amendia:calledVersion``; absent → :data:`DEFAULT_CALL_VERSION_RANGE`). Nested-instance
    execution is deferred (documented stretch). Captured regardless of profile; refused under
    ``common_subset`` and for the deferred stretches (MI host / boundary on a callActivity)."""

    id: str
    target_pack: Optional[str]           # calledElement = callee pack_key (None = no target → refused)
    version_range: str = "^1.0.0"        # amendia:calledVersion (a semver range; policy default below)
    parent_scope: str = ""               # containing scope (process_id or a parent subProcess id)
    is_multi_instance: bool = False      # a callActivity as a MI host is a deferred stretch (refused)


# Policy default when a callActivity declares no ``amendia:calledVersion`` — the conservative "latest
# compatible 1.x". Documented so a diagram without an explicit range still pins reproducibly (ADR-039).
DEFAULT_CALL_VERSION_RANGE = "^1.0.0"


@dataclass
class EventSubProcess:
    """An event ``subProcess`` (``triggeredByEvent="true"``) — a **scope-wide event handler** (ADR-042
    / Backlog #5, Item F). Unlike a boundary on a subProcess (ADR-041), its trigger start event makes it
    fire from **anywhere in its enclosing scope**, and that scope may be the whole **process** (which a
    subProcess boundary cannot express). Only **interrupting** ``error``/``timer`` starts run: on trigger
    the enclosing scope is cancelled (reusing ADR-041's scope machinery) and the ESP **body is inlined**
    as the handler. It is therefore *not* a :class:`SubProcess` (no parent-level in/out flow, its body
    ends are terminal); the compiler registers the handler as a scope boundary on ``enclosing_scope`` and
    splices the body's start-successor as the handler entry.

    ``trigger`` is ``"error"`` or ``"timer"`` when runnable; ``unsupported`` (set → refused by the
    compilability gate) records why a message/signal/escalation start or a non-interrupting ESP cannot
    run. ``error_code`` is the matched code (``None`` = catch-all); ``timer`` the schedule.
    ``body_start_successor`` is the start event's single outgoing target — the inlined handler's first
    node; ``end_ids`` are the body's terminal ends."""

    id: str
    enclosing_scope: str                 # process_id or the enclosing subProcess id (scope it guards)
    trigger: Optional[str] = None        # "error" | "timer" (None when unsupported)
    error_code: Optional[str] = None     # matched raised code; None = catch-all (error trigger)
    timer: Optional["TimerDef"] = None   # schedule (timer trigger)
    is_interrupting: bool = True         # isInterrupting != "false" (non-interrupting deferred)
    start_id: Optional[str] = None       # the ESP's trigger start event id (plumbing, not a graph node)
    body_start_successor: Optional[str] = None  # start's outgoing target = the inlined handler entry
    end_ids: List[str] = field(default_factory=list)  # the body's terminal end events
    unsupported: Optional[str] = None    # reason string when refused (message/signal/escalation, non-interrupting)


@dataclass
class CompensationHandler:
    """A compensation handler pairing (ADR-043 / Backlog #4, Item G). A handler activity
    (``isForCompensation="true"``, off the sequence flow, bound to an **undo** capability) is paired to
    a **compensable primary** activity by a compensation ``boundaryEvent`` (a ``compensateEventDefinition``
    whose ``attachedToRef`` is the primary) plus an ``association`` (boundary → handler). When a
    compensate-throw fires, the primary's completed side effect is reversed by running ``handler_id``."""

    handler_id: str                  # the isForCompensation activity (bound undo capability)
    primary_id: str                  # the compensable activity whose side effect it reverses
    boundary_id: str                 # the compensation boundaryEvent that pairs them


@dataclass
class CompensateThrow:
    """A compensate throw event (ADR-043) — an ``intermediateThrowEvent``/``endEvent`` carrying a
    ``compensateEventDefinition``. When reached it compensates its enclosing scope's completed
    compensable activities in **reverse (LIFO) order**. This cut is **scope-wide**: a targeted throw
    (``activityRef`` → one activity) is refused (deferred stretch). ``is_end`` distinguishes a terminal
    end-event throw (compensate, then the instance ends) from an intermediate throw (compensate, then
    continue via the outgoing flow)."""

    id: str
    scope: str                       # enclosing scope id (its compensable activities are compensated)
    is_end: bool = False             # an endEvent throw (terminal) vs an intermediateThrowEvent
    activity_ref: Optional[str] = None   # targeted compensation (deferred → refused); None = scope-wide


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
    # ADR-027 Phase 2.2 (timers rung). Populated regardless of profile (like parallel_gateways) —
    # the profile only decides the coverage *tier*; the compiler + compilability gate read these
    # to wire/reject execution. A timer intermediateCatchEvent parks the instance for a duration;
    # a boundary timer on a HITL gate fires the escalation flow. Only *wired* constructs land here.
    timer_catch_events: Dict[str, "TimerDef"] = field(default_factory=dict)   # catch event id -> schedule
    boundary_timers: Dict[str, "BoundaryTimer"] = field(default_factory=dict)  # host activity id -> timer
    # ADR-030 (Phase 2.3): host task id -> its error boundary events (a task may catch several codes).
    error_boundaries: Dict[str, List["ErrorBoundary"]] = field(default_factory=dict)
    # ADR-031 (Phase 2.4): inbound message constructs. Values are the BPMN message name (via
    # messageRef → <bpmn:message name>) when present — advisory; the runtime correlates by the
    # manifest binding's message_name. Captured regardless of profile (profile gates the tier).
    message_catch_events: Dict[str, Optional[str]] = field(default_factory=dict)  # catch event id -> msg name
    receive_tasks: Dict[str, Optional[str]] = field(default_factory=dict)         # receiveTask id -> msg name
    # eventBasedGateway id -> its arm catch-event ids (outgoing flow targets), in document order.
    event_based_gateways: Dict[str, List[str]] = field(default_factory=dict)
    # ADR-032 (Phase 2.6): embedded sub-processes (container id -> SubProcess), the scope each element
    # belongs to (element id -> scope id), nested start/end ids (plumbing, not graph nodes), and the
    # deferred constructs the compilability gate always refuses.
    subprocesses: Dict[str, "SubProcess"] = field(default_factory=dict)
    # ADR-036 (Backlog #3): host activity id -> its multi-instance loop characteristics. Populated for
    # task hosts (executable under common_executable) and subProcess hosts (refused — deferred stretch),
    # regardless of profile (like the other construct dicts); the compilability gate decides runnability.
    multi_instance: Dict[str, "MultiInstance"] = field(default_factory=dict)
    element_scope: Dict[str, str] = field(default_factory=dict)   # element id -> containing scope id
    nested_starts: Set[str] = field(default_factory=set)          # sub-process start-event ids
    nested_ends: Set[str] = field(default_factory=set)            # sub-process end-event ids
    # ADR-039: callActivity id -> its cross-pack target (calledElement + version range). Captured
    # regardless of profile (like the other construct dicts); the compiler inline-splices the callee.
    call_activities: Dict[str, "CallActivity"] = field(default_factory=dict)
    subprocess_boundaries: List[str] = field(default_factory=list)  # boundary attached to a subProcess (deferred)
    # ADR-042 (Backlog #5, Item F): event sub-processes (triggeredByEvent="true") — scope-wide handlers
    # keyed by their container id. A runnable ESP's handler is ALSO registered into boundary_timers /
    # error_boundaries[enclosing_scope] (so the compiler reuses ADR-041's scope router); this dict is the
    # authoritative record (trigger kind, refusal reason, body ends) the compiler + gate read.
    event_subprocesses: Dict[str, "EventSubProcess"] = field(default_factory=dict)
    # ADR-043 (Backlog #4, Item G): compensation. ``compensation_handlers`` (handler_id -> pairing) are
    # the off-flow ``isForCompensation`` activities each paired via a compensate boundaryEvent+association
    # to a compensable primary; ``compensations`` (primary_id -> handler_id) is the convenience inverse
    # the compiler threads onto the primary's node (to log a compensation entry on commit).
    # ``compensate_throws`` (throw_id -> CompensateThrow) are the compensate-throw events that drive the
    # reverse-order undo. Off-flow handler activities are excluded from reachability/arity like an ESP body.
    compensation_handlers: Dict[str, "CompensationHandler"] = field(default_factory=dict)
    compensations: Dict[str, str] = field(default_factory=dict)   # primary_id -> handler_id
    compensate_throws: Dict[str, "CompensateThrow"] = field(default_factory=dict)
    cancel_end_events: List[str] = field(default_factory=list)    # endEvents with a cancelEventDefinition
    # ADR-033 (Phase 2.7): businessRuleTask id -> its advisory decisionRef/calledDecision (inference
    # only — native DMN is NOT evaluated); scriptTask ids that carry an inline <script> body (refused).
    decision_refs: Dict[str, str] = field(default_factory=dict)
    inline_scripts: List[str] = field(default_factory=list)
    # ADR-027: every element the parser saw, tagged by tier. The typed collections above stay
    # "executable only"; this is the separate retention surface for documented/unknown elements.
    elements: List[ClassifiedElement] = field(default_factory=list)

    def outgoing(self, node_id: str) -> List[Flow]:
        return [f for f in self.flows if f.source == node_id]

    def bindable_elements(self) -> Dict[str, str]:
        """element_id -> its binding ``element_kind`` for every element that MUST carry a manifest
        binding: serviceTask/userTask (capability/human) + messageCatch/receiveTask (message). Used
        by the registry bijection and the runtime node-context builder (ADR-031)."""
        out: Dict[str, str] = dict(self.tasks)  # serviceTask | userTask
        for cid in self.message_catch_events:
            out[cid] = "messageCatch"
        for rid in self.receive_tasks:
            out[rid] = "receiveTask"
        for aid in self.call_activities:        # ADR-039 — a callActivity binds a `call` executor
            out[aid] = "callActivity"
        return out

    def coverage(self) -> Dict[str, Any]:
        """Coverage report: per-tier counts + the documented/unknown element lists (used by the
        registry/onboarding to build the coverage overlay)."""
        counts = {tier: 0 for tier in ELEMENT_TIERS}
        for e in self.elements:
            counts[e.tier] = counts.get(e.tier, 0) + 1
        return {
            "counts": counts,
            "documented": [e for e in self.elements if e.tier == "documented"],
            "unknown": [e for e in self.elements if e.tier == "unknown"],
        }
