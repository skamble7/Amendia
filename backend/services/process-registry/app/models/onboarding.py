# app/models/onboarding.py
"""OnboardingSession aggregate + wizard request/response models.

The session is a **registry-owned authoring scratch space** (collection
``onboarding_sessions``), NOT a contract document. It accumulates *staged* artifact
schemas, capabilities, bindings, triage rules and policies as the operator walks the
form-driven wizard; nothing is written to the shared catalog collections until
``commit`` (see ``app.services.onboarding``). Because staged pieces are plain draft
data, these models use permissive pydantic (not the strict ``ContractModel``); the
strict contract models are composed at *assemble* time.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from amendia_contracts.common import utcnow


# --------------------------------------------------------------------------- #
# State machine
# --------------------------------------------------------------------------- #

class OnboardingState(str, Enum):
    """Explicit state machine. Each transition endpoint advances (or, on an upstream
    edit, regresses) this. The pack lifecycle (draft→validated→active) is separate —
    the pack does not exist until ``commit``."""

    INITIATED = "initiated"                    # basics stored
    BPMN_ATTACHED = "bpmn_attached"            # BPMN parsed, inventory derived
    CAPABILITIES_RESOLVED = "capabilities_resolved"  # mcp caps staged + reuse refs recorded
    BINDINGS_SET = "bindings_set"              # one binding per task, guards passed
    TRIAGE_SET = "triage_set"                  # triage predicate trees stored
    POLICIES_SET = "policies_set"              # gateway vars, SoD, pack-local roles
    ASSEMBLED = "assembled"                    # manifest composed + dry-run validated
    COMPLETED = "completed"                    # committed → pack active (terminal)


# Ordering used for guard checks ("at least at state X") and regression clamps.
_STATE_ORDER: List[OnboardingState] = [
    OnboardingState.INITIATED,
    OnboardingState.BPMN_ATTACHED,
    OnboardingState.CAPABILITIES_RESOLVED,
    OnboardingState.BINDINGS_SET,
    OnboardingState.TRIAGE_SET,
    OnboardingState.POLICIES_SET,
    OnboardingState.ASSEMBLED,
    OnboardingState.COMPLETED,
]


def state_rank(state: OnboardingState) -> int:
    return _STATE_ORDER.index(state)


# --------------------------------------------------------------------------- #
# Staged sub-documents (composed into strict contract models at assemble time)
# --------------------------------------------------------------------------- #

class Basics(BaseModel):
    pack_key: str
    version: str
    title: str
    description: Optional[str] = None
    default_domain: str          # the capability/artifact id namespace — always set (see create())


class DocumentedElement(BaseModel):
    """A retained BPMN element outside the executable set (ADR-027 coverage overlay)."""

    element_id: Optional[str] = None
    kind: str                                                  # BPMN local-name
    tier: str                                                  # documented | unknown


# -- Semantic summary (ADR-027 Phase 1.1): the diagram's meaning, for the UI + inference -- #

class LaneSummary(BaseModel):
    id: str
    name: Optional[str] = None
    member_ids: List[str] = Field(default_factory=list)


class PoolSummary(BaseModel):
    id: str
    name: Optional[str] = None
    is_external: bool = False


class MessageFlowSummary(BaseModel):
    id: str
    name: Optional[str] = None
    source: Optional[str] = None
    target: Optional[str] = None


class EventSummary(BaseModel):
    id: str
    name: Optional[str] = None
    subtype: Optional[str] = None                             # message | timer | error | ...
    attached_to: Optional[str] = None                         # boundaryEvent host


class GatewayConditionSummary(BaseModel):
    gateway_id: str
    flow_id: str
    variable: Optional[str] = None                            # leading dot-path of the condition
    raw: str


class DataObjectSummary(BaseModel):
    id: str
    name: Optional[str] = None


# -- Inference draft (ADR-027 Phase 1.2): ADVISORY pre-fills derived from the diagram. Never
#    authoritative — the operator's step submissions write the staged_* fields. -- #

class InferredRole(BaseModel):
    role_id: str
    label: str
    source_lane: Optional[str] = None
    # ADR-045 (Track 3): a persona description derived from the lane's role in the process (approver /
    # analyst / agent / supervisor). Seeds the Policies step's role_meta description; operator-editable.
    description: Optional[str] = None


class InferredBinding(BaseModel):
    element_id: str
    element_kind: str                                         # full bindable task/message/call kinds
    executor_type: str                                        # capability | human | message | call
    suggested_role: Optional[str] = None
    # Batch-2: the inferred capability id (cap.<domain>.<name>) for a capability element — the Bindings
    # step pre-selects the matching staged/reused capability. None for human/message/call.
    suggested_capability_id: Optional[str] = None
    # ADR-048: input-source suggestion for a capability task. At BPMN-attach this is the coarse
    # graph-position hint ({"from":"trigger"} entry / {"from":"artifact","element":<up>} downstream); once
    # capabilities are staged, ``refine_input_sources`` REPLACES it with a field-level ``input_map`` — the
    # binding's input name → an InputSource that may be a composite ``{"fields":{…}}`` matching each input
    # field to an upstream output field or a trigger path. None/empty for human/message/call.
    suggested_input_source: Optional[Dict[str, Any]] = None
    # ADR-048 D4: every upstream CAPABILITY element reachable on the flows into this node (nearest-first).
    # The field-level refinement matches this node's input fields against these elements' output schemas.
    upstream_caps: List[str] = Field(default_factory=list)
    # ADR-050: every upstream PRODUCER element (capability + human/message/call whose binding may declare an
    # output) reachable on the flows into this node, nearest-first, terminating at the first producer on each
    # branch. Superset of ``upstream_caps`` — lets a capability input source from a human-authored artifact.
    upstream_producers: List[str] = Field(default_factory=list)
    # ADR-051: when this capability task's output feeds an exclusiveGateway, the gateway condition's first
    # segment (e.g. ``validation`` from ``validation.order_verdict``) — the name the runtime needs the output to
    # carry for the gateway to branch. The Bindings step defaults the capability's output name to this. None ⇒
    # the task feeds no gateway ⇒ the output keeps its ``<tool>_output`` default.
    suggested_output_name: Optional[str] = None
    suggested_hitl_mode: str = "none"
    source_lane: Optional[str] = None


class InferredGatewayVariable(BaseModel):
    gateway_id: str
    variable: str


class CapabilityCandidate(BaseModel):
    source: str                                               # element id or message-flow id
    suggested_capability_id: str
    kind_hint: str = "mcp"
    needs_endpoint: bool = True


class ArtifactSeed(BaseModel):
    suggested_artifact_key: str
    source: str


class SodCandidate(BaseModel):
    elements: List[str] = Field(default_factory=list)
    rationale: str


class InferenceAnnotation(BaseModel):
    code: str
    element_id: Optional[str] = None
    message: str


class InferenceDraft(BaseModel):
    roles: List[InferredRole] = Field(default_factory=list)
    bindings: List[InferredBinding] = Field(default_factory=list)
    gateway_variables: List[InferredGatewayVariable] = Field(default_factory=list)
    capability_candidates: List[CapabilityCandidate] = Field(default_factory=list)
    artifact_seeds: List[ArtifactSeed] = Field(default_factory=list)
    sod_candidates: List[SodCandidate] = Field(default_factory=list)
    annotations: List[InferenceAnnotation] = Field(default_factory=list)


class SubProcessSummary(BaseModel):
    """ADR-032 Phase 2.6: an embedded sub-process for the coverage overlay + bindings grouping."""

    id: str
    name: Optional[str] = None
    member_ids: List[str] = Field(default_factory=list)


class BindableElementSummary(BaseModel):
    """ADR-044 (Track 1): one BPMN element the operator must bind, sourced from the parsed
    ``amendia_bpmn`` model's ``bindable_elements()`` (the full standard task set + message elements +
    callActivity). ``category`` routes to the executor sub-form (``TASK_EXECUTOR_CATEGORY``); the
    ``subProcess``/event-subprocess **containers** are never in this list. Per-element metadata drives
    the binding UI (badges) without re-deriving from the diagram."""

    element_id: str
    element_kind: str                                          # serviceTask|userTask|sendTask|scriptTask|
    #                                                            manualTask|businessRuleTask|receiveTask|
    #                                                            messageCatch|callActivity
    category: str                                              # capability | human | message | call
    name: Optional[str] = None
    is_multi_instance: bool = False                            # ADR-036 — runs N times (badge)
    is_for_compensation: bool = False                          # ADR-043 — an off-flow undo handler (badge)
    compensation_primary: Optional[str] = None                # the activity this handler compensates
    in_event_subprocess: bool = False                         # ADR-042 — lives in an ESP body (binds normally)
    message_name: Optional[str] = None                        # message elements — advisory BPMN message name
    called_pack: Optional[str] = None                         # callActivity — calledElement (pack_key)
    called_version: Optional[str] = None                      # callActivity — amendia:calledVersion range


class BpmnInventory(BaseModel):
    """Parsed BPMN topology the downstream steps hang off of, plus the ADR-027 coverage report."""

    process_id: str
    bpmn_file: str
    sha256: str
    # ADR-044 (Track 1): the AUTHORITATIVE full bindable set (task kinds + message + callActivity) the
    # bindings step + bijection consume. ``service_tasks``/``user_tasks`` are retained as legacy
    # serviceTask-only / userTask-only views (markers, coverage groups) — a strict subset of the above.
    bindable_elements: List[BindableElementSummary] = Field(default_factory=list)
    service_tasks: List[str] = Field(default_factory=list)
    user_tasks: List[str] = Field(default_factory=list)
    gateways: List[str] = Field(default_factory=list)          # exclusive gateways
    task_names: Dict[str, str] = Field(default_factory=dict)   # id -> human name (best effort)
    # ADR-032 Phase 2.6: embedded sub-processes (id -> members) for grouping nested tasks in the UI.
    subprocesses: List[SubProcessSummary] = Field(default_factory=list)
    # Coverage (Phase 0): what will execute vs what is documented-only. Phase 1 deepens topology.
    documented_elements: List[DocumentedElement] = Field(default_factory=list)
    coverage_counts: Dict[str, int] = Field(default_factory=dict)  # {executable, documented, unknown}
    # ADR-027 Phase 2.5: the minimum execution profile this diagram needs (derived: "parallel" iff it
    # has parallel gateways, else "common_subset"). Pinned into the resolution sidecar at activation;
    # surfaced here pre-activation so the onboarding Review step can flag "requires parallel profile".
    required_execution_profile: str = "common_subset"
    # Semantic summary (Phase 1.1): the diagram's meaning the UI renders + inference consumes.
    lanes: List[LaneSummary] = Field(default_factory=list)
    pools: List[PoolSummary] = Field(default_factory=list)
    message_flows: List[MessageFlowSummary] = Field(default_factory=list)
    events: List[EventSummary] = Field(default_factory=list)
    gateway_conditions: List[GatewayConditionSummary] = Field(default_factory=list)
    data_objects: List[DataObjectSummary] = Field(default_factory=list)


class StagedArtifact(BaseModel):
    """A to-be-registered artifact schema, inferred from an MCP tool's in/out schema."""

    artifact_key: str
    version: str
    title: str
    description: Optional[str] = None
    json_schema: Dict[str, Any]
    compatibility: str = "backward"
    source_tool: Optional[str] = None


class StagedCapability(BaseModel):
    """A to-be-registered capability. ``kind: mcp`` is inferred from one MCP tool (endpoint/tool set);
    ADR-046 (Track 2) adds inline-configured ``kind: decision`` (a DMN ``table``) and ``kind: reduce`` (a
    ``config``) authored directly in the wizard — no endpoint, always ``read_only``.

    ``input_artifact_key`` / ``output_artifact_key`` reference ``StagedArtifact``s (or an existing
    artifact, for a decision/reduce input) by key."""

    capability_id: str
    version: str
    title: str
    description: Optional[str] = None
    kind: str = "mcp"                       # mcp | decision | reduce (ADR-046)
    side_effect: str = "read_only"          # read_only | side_effectful (decision/reduce always read_only)
    idempotent: Optional[bool] = None
    min_hitl_mode: Optional[str] = None
    # IO — one input + one output artifact.
    input_name: str
    input_artifact_key: str
    output_name: str
    output_artifact_key: str
    # Runtime (self-descriptive MCP, ADR-024) — mcp only.
    endpoint: Optional[str] = None
    tool: Optional[str] = None
    transport: str = "streamable_http"
    headers: Dict[str, str] = Field(default_factory=dict)
    source_tool: Optional[str] = None
    # ADR-046: the inline runtime payload for a decision (DMN table) / reduce (config) capability.
    table: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None


class StagedBindingIO(BaseModel):
    name: str
    schema_ref: str                          # art.<...>@<range>
    required: bool = True


class StagedBinding(BaseModel):
    element_id: str
    element_kind: str                        # full standard task set + messageCatch/receiveTask/callActivity
    executor_type: str                       # capability | human | message | call
    capability_ref: Optional[str] = None     # cap.<...>@<range> (capability executor)
    role: Optional[str] = None               # role.<...>       (human executor)
    assist_capability_ref: Optional[str] = None
    hitl_mode: str = "none"
    hitl_role: Optional[str] = None
    # ADR-031 message executor: the business message this element awaits (no capability, no HITL).
    message_name: Optional[str] = None
    # ADR-039 call executor: the callee pack + range + IO maps (no capability, no HITL of its own).
    call_pack: Optional[str] = None
    call_version: Optional[str] = None
    input_map: Dict[str, str] = Field(default_factory=dict)     # callee_input_binding -> caller dotpath
    output_map: Dict[str, str] = Field(default_factory=dict)    # caller_artifact -> callee_output_binding
    # ADR-048: per-input data source (binding input name -> InputSource dict) for a CAPABILITY binding —
    # composed into the manifest Binding.input_map. Distinct from the call executor's input_map above.
    input_sources: Dict[str, Any] = Field(default_factory=dict)
    inputs: List[StagedBindingIO] = Field(default_factory=list)
    outputs: List[StagedBindingIO] = Field(default_factory=list)


class StagedTriageRule(BaseModel):
    rule_id: str
    priority: int = 100
    description: Optional[str] = None
    when: Dict[str, Any]                     # predicate tree (all/any/not + {field,op,value})


class StagedGatewayVariable(BaseModel):
    gateway_id: str
    variable: str
    source_artifact: str                     # art.<...> (bare, no version)


class StagedSod(BaseModel):
    elements: List[str] = Field(default_factory=list)


class RoleMeta(BaseModel):
    """Operator-authored label/description for a pack-local role id (UX/governance only)."""

    label: Optional[str] = None
    description: Optional[str] = None


class CommitStep(BaseModel):
    key: str
    label: str
    status: str = "pending"                  # pending | running | done | failed
    detail: Optional[str] = None


# --------------------------------------------------------------------------- #
# The aggregate
# --------------------------------------------------------------------------- #

class OnboardingSession(BaseModel):
    session_id: str
    created_by: str                          # amendia usr-… from the bearer
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    state: OnboardingState = OnboardingState.INITIATED

    basics: Basics
    # Batch-4: the pack's trigger field/type map (dotpath -> json type), derived from the deployment sample
    # envelopes at create. Drives schema-aware triage authoring (field picker + type-valid ops). Empty when no
    # trigger schema is available (the Triage step then falls back to free-text + structural checks only).
    trigger_fields: Dict[str, str] = Field(default_factory=dict)
    # ADR-049: the operator-DECLARED trigger artifact schema (art.<domain>.<name>). When set, trigger_fields is
    # flattened from THIS schema (not the sample envelopes), and it is registered + emitted as the manifest's
    # ProcessPack.trigger. None ⇒ fall back to the deployment sample envelopes (opaque if there are none).
    trigger_artifact: Optional[StagedArtifact] = None
    # ADR-050: operator-authored artifact schemas that are neither a tool's I/O nor the trigger (e.g.
    # art.dining.order, a human task's output shape). Kept apart from ``staged_artifacts`` — which
    # ``set_capabilities`` rebuilds wholesale from introspection — so re-staging capabilities never drops
    # them. Registered + listed among the pack artifacts at assemble, and referenceable by a binding output.
    authored_artifacts: List[StagedArtifact] = Field(default_factory=list)
    bpmn: Optional[BpmnInventory] = None
    staged_artifacts: List[StagedArtifact] = Field(default_factory=list)
    staged_capabilities: List[StagedCapability] = Field(default_factory=list)
    reused_capability_refs: List[str] = Field(default_factory=list)
    bindings: List[StagedBinding] = Field(default_factory=list)
    triage_rules: List[StagedTriageRule] = Field(default_factory=list)
    gateway_variables: List[StagedGatewayVariable] = Field(default_factory=list)
    sod_policies: List[StagedSod] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    role_meta: Dict[str, RoleMeta] = Field(default_factory=dict)  # role_id -> label/description
    inferred: Optional[InferenceDraft] = None                    # ADR-027 Phase 1: advisory pre-fills

    dry_run_report: Optional[Dict[str, Any]] = None
    commit_progress: List[CommitStep] = Field(default_factory=list)
    result_pack: Optional[str] = None        # pack_key@version once committed

    # ADR-052 Phase 2a: the copilot's plain-language summary + per-decision provenance + open questions,
    # persisted when a session was generated by the copilot. Additive session state (NOT a manifest field) —
    # the 2b conversation and 2c business review stand on it. None for a hand-driven session.
    copilot_report: Optional["CopilotReport"] = None
    # ADR-052 Phase 2b: the natural-language refine transcript (operator message → applied changes → reply),
    # the design-sign-off audit trail + the input to 2c's review. Empty until the copilot chat is used.
    conversation: List["ConversationTurn"] = Field(default_factory=list)

    # Set on each mutation so the UI can explain the invalidation cascade.
    last_cleared: List[str] = Field(default_factory=list)

    def to_doc(self) -> dict:
        return self.model_dump(mode="json")

    def at_least(self, state: OnboardingState) -> bool:
        return state_rank(self.state) >= state_rank(state)


# --------------------------------------------------------------------------- #
# Request bodies (wizard step payloads)
# --------------------------------------------------------------------------- #

class CreateSessionRequest(BaseModel):
    pack_key: str
    version: str
    title: str
    description: Optional[str] = None
    # The capability/artifact id namespace (cap.<domain>.<tool>). Operator-supplied; when omitted it
    # derives deterministically from the pack_key (sanitized) — never a hardcoded business area. Keeping
    # it process-scoped avoids colliding with an active catalog capability id.
    default_domain: Optional[str] = None


class AttachBpmnRequest(BaseModel):
    bpmn_xml: str
    bpmn_file: Optional[str] = None          # display name; defaults to <pack_key>.bpmn


class CapabilityToolSelection(BaseModel):
    """One selected MCP tool + operator-edited inferred ids and classification."""

    tool: str
    endpoint: str
    transport: str = "streamable_http"
    headers: Dict[str, str] = Field(default_factory=dict)
    domain: Optional[str] = None             # defaults to session default_domain
    # Editable inferred ids (server re-normalizes / suggests when omitted).
    input_artifact_key: Optional[str] = None
    output_artifact_key: Optional[str] = None
    capability_id: Optional[str] = None
    artifact_version: str = "1.0.0"
    capability_version: str = "1.0.0"
    side_effect: str = "read_only"
    idempotent: Optional[bool] = None
    min_hitl_mode: Optional[str] = None
    # The raw tool schemas as returned by introspection (so the server can re-infer
    # without a second round-trip to the MCP server).
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    title: Optional[str] = None
    description: Optional[str] = None


class DecisionSpec(BaseModel):
    """ADR-046 (Track 2): author a native-DMN ``decision`` capability inline (no code, no MCP). The
    ``table`` is the normalized DMN shape (``{hit_policy, inputs, outputs, rules}``); it is structurally
    validated on stage by the shared ``amendia_bpmn.dmn`` checks. The **verdict** output artifact is
    inferred from the table's outputs (each column → a required field a gateway can branch on); the
    **input** references an existing/staged upstream artifact whose fields the input expressions read."""

    capability_id: str                       # cap.<domain>.<name> (editable)
    title: Optional[str] = None
    description: Optional[str] = None
    capability_version: str = "1.0.0"
    table: Dict[str, Any]                    # the normalized decision table
    input_artifact_key: str                  # the upstream artifact the table reads (staged or reused)
    input_name: str = "in"
    output_artifact_key: str                 # the verdict artifact to create
    output_name: str = "verdict"
    output_version: str = "1.0.0"


class ReduceSpec(BaseModel):
    """ADR-046 (Track 2): author a ``reduce`` capability inline. The ``config`` is the normalized reduce
    shape (``{op, source?, item_path?, predicate?, output_field}``), structurally validated on stage by
    ``amendia_bpmn.reduce``. The **summary** output artifact is inferred from ``output_field`` + the op's
    result type; the **input** references an existing/staged **list** artifact."""

    capability_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    capability_version: str = "1.0.0"
    config: Dict[str, Any]                   # the normalized reduce config
    input_artifact_key: str                  # the upstream list artifact
    input_name: str = "in"
    output_artifact_key: str                 # the summary artifact to create
    output_name: str = "summary"
    output_version: str = "1.0.0"


class SetCapabilitiesRequest(BaseModel):
    tools: List[CapabilityToolSelection] = Field(default_factory=list)
    # ADR-046: inline-authored decision / reduce capabilities, staged alongside the MCP tools.
    decision_specs: List[DecisionSpec] = Field(default_factory=list)
    reduce_specs: List[ReduceSpec] = Field(default_factory=list)
    reused_capability_refs: List[str] = Field(default_factory=list)


class BindingInput(BaseModel):
    element_id: str
    element_kind: str
    executor_type: str                       # capability | human | message | call
    capability_ref: Optional[str] = None
    role: Optional[str] = None
    assist_capability_ref: Optional[str] = None
    hitl_mode: str = "none"
    hitl_role: Optional[str] = None
    # ADR-044 (Track 1): message + call executor authoring (mirrors the manifest Executor union).
    message_name: Optional[str] = None
    call_pack: Optional[str] = None
    call_version: Optional[str] = None
    input_map: Dict[str, str] = Field(default_factory=dict)
    output_map: Dict[str, str] = Field(default_factory=dict)
    # ADR-048: per-input data sourcing (input name -> InputSource) — where each input's data comes from. Used by
    # a CAPABILITY binding (auto-derived from the bound tool + upstream producers) AND, symmetrically, by a HUMAN
    # binding to source the read-only context artifacts it declares in ``inputs`` from an upstream output.
    input_sources: Dict[str, Any] = Field(default_factory=dict)
    # ADR-050 + ADR-048: a human/message binding may DECLARE the artifact(s) it produces AND the ones it reads as
    # read-only context — each ``schema_ref`` referencing a staged/authored/trigger artifact (its source is in
    # ``input_sources``). Ignored for a capability binding (IO mirrored from the tool) and call (uses input/output_map).
    inputs: List[StagedBindingIO] = Field(default_factory=list)
    outputs: List[StagedBindingIO] = Field(default_factory=list)
    # ADR-051: a settable OUTPUT NAME for a CAPABILITY binding — the runtime resolves gateway conditions against
    # binding output names (``validation.order_verdict`` needs an output literally named ``validation``), so the
    # name must be authorable, not forced to ``<tool>_output``. Renames the mirrored output; schema_ref is
    # unchanged. None ⇒ default from the fed gateway's condition, else ``<tool>_output``.
    output_name: Optional[str] = None


class SetBindingsRequest(BaseModel):
    bindings: List[BindingInput] = Field(default_factory=list)


class DeclareTriggerRequest(BaseModel):
    """ADR-049: declare the pack's trigger artifact schema. The operator provides the trigger JSON-Schema
    (registered as ``art.<domain>.<name>``); it drives the Triage field picker and is emitted as
    ``ProcessPack.trigger``. Same shape as a :class:`StagedArtifact`, but operator-authored, not introspected."""

    artifact_key: str
    version: str = "1.0.0"
    title: str
    description: Optional[str] = None
    json_schema: Dict[str, Any]


class DeclareArtifactRequest(BaseModel):
    """ADR-050: declare (upsert) an operator-authored artifact schema — one that is neither a tool's I/O nor
    the trigger (e.g. ``art.dining.order``, the shape a human task produces). Same fields as a trigger
    declaration; stored on ``authored_artifacts`` and registered like any staged schema at assemble. A
    binding output may then reference it by ``schema_ref``."""

    artifact_key: str
    version: str = "1.0.0"
    title: str
    description: Optional[str] = None
    json_schema: Dict[str, Any]


class RefineArtifactRequest(BaseModel):
    """ADR-054: refine an existing HUMAN-authored artifact's JSON schema (typed properties, JSON-Schema ``title``
    labels, enums, ``required``) so the runtime HITL form renders labeled/typed fields, not a raw JSON blob. Unlike
    DeclareArtifactRequest the version is resolved SERVER-side (bump-on-change vs the registered body), so the
    caller sends only the key + refined schema (+ optional title); the referencing bindings are re-pinned to it."""

    artifact_key: str
    json_schema: Dict[str, Any]
    title: Optional[str] = None


class SetTriageRequest(BaseModel):
    triage_rules: List[StagedTriageRule] = Field(default_factory=list)


class SetPoliciesRequest(BaseModel):
    gateway_variables: List[StagedGatewayVariable] = Field(default_factory=list)
    sod_policies: List[StagedSod] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    role_meta: Dict[str, RoleMeta] = Field(default_factory=dict)  # role_id -> label/description


# --------------------------------------------------------------------------- #
# MCP introspection request/response
# --------------------------------------------------------------------------- #

class IntrospectMcpRequest(BaseModel):
    endpoint: str
    transport: str = "streamable_http"
    headers: Dict[str, str] = Field(default_factory=dict)
    domain: Optional[str] = None             # required to seed suggested ids (no business-area default)


class ToolCompliance(BaseModel):
    compliant: bool
    reasons: List[str] = Field(default_factory=list)


class IdCollision(BaseModel):
    """Batch-4: the derived ``cap.<domain>.<tool>`` id already exists as an ACTIVE catalog capability. A
    **hard** collision means that active capability's contract (kind and/or input/output artifact keys)
    DIFFERS from what introspection would stage — binding this pack to it later fails ``binding_io_mismatch``;
    steer the operator to a distinct domain or explicit reuse. A **benign** match means the active descriptor
    is contract-compatible (same ``kind: mcp`` + same IO artifact keys) — not a clash but a reuse opportunity.
    Advisory only (non-blocking): the operator decides domain-vs-reuse."""

    capability_id: str
    severity: str                            # "hard" | "benign"
    active_version: str
    active_kind: str
    diff: str                                # human-readable active-vs-introspected contract diff


class IntrospectedTool(BaseModel):
    name: str
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    compliance: ToolCompliance
    # Suggested (editable) inferred ids — only when compliant.
    suggested_input_artifact_key: Optional[str] = None
    suggested_output_artifact_key: Optional[str] = None
    suggested_capability_id: Optional[str] = None
    # ADR-052 E3: side-effect default — `side_effectful` when the tool OUTPUT carries the acknowledgement shape
    # (acknowledged + action_id + status), else `read_only`. Operator-overridable in the Capabilities step.
    suggested_side_effect: str = "read_only"
    # Batch-4: set when the derived id collides with an active catalog capability (advisory).
    id_collision: Optional[IdCollision] = None


class IntrospectMcpResponse(BaseModel):
    endpoint: str
    transport: str
    tools: List[IntrospectedTool] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# ADR-052 Phase 2a — the onboarding copilot (generation core)
# --------------------------------------------------------------------------- #

class CopilotDecision(BaseModel):
    """One provenance entry: what the copilot decided, WHO decided it (the deterministic engine vs the LLM),
    and why. The 2b conversation and 2c review render these so a human can audit every generated choice."""

    kind: str                                # binding | executor | hitl | output_name | input_map | human_artifact | trigger | triage
    element_id: Optional[str] = None
    decided_by: str                          # "deterministic" | "llm"
    summary: str                             # plain-language ("bound Validate order → validate_order")
    rationale: Optional[str] = None          # the LLM's one-line rationale, or the deterministic rule applied
    confidence: Optional[float] = None       # the LLM's self-reported confidence (absent for deterministic)


class CopilotOpenQuestion(BaseModel):
    """A low-confidence or discretionary decision the 2b conversation should confirm with the operator."""

    topic: str                               # tool_match | hitl_gate | triage | trigger | ...
    question: str
    element_id: Optional[str] = None
    confidence: Optional[float] = None


class CopilotReport(BaseModel):
    """The artifact 2b/2c stand on: a plain-language process summary, per-decision provenance, and the open
    questions. Persisted on the session by a copilot-generated run; additive (never part of the manifest)."""

    summary: str = ""
    decisions: List[CopilotDecision] = Field(default_factory=list)
    open_questions: List[CopilotOpenQuestion] = Field(default_factory=list)
    llm_used: bool = True                    # false when the copilot ran with the LLM disabled / a supplied proposal
    model_ref: Optional[str] = None          # the ConfigForge ref the semantic call resolved (never a raw key)
    repair_passes: int = 0                   # how many validator-repair rounds ran


class CopilotMcpConfig(BaseModel):
    endpoint: str
    transport: str = "streamable_http"
    headers: Dict[str, str] = Field(default_factory=dict)


class CopilotGenerateRequest(BaseModel):
    """Body for ``POST /onboarding/copilot/generate`` — a comprehensive BPMN + a live MCP endpoint in, a
    populated validator-clean draft session out."""

    pack_key: str
    version: str = "1.0.0"
    title: str
    description: Optional[str] = None
    domain: Optional[str] = None             # defaults from pack_key (mirrors CreateSessionRequest)
    bpmn_xml: str
    bpmn_file: Optional[str] = None
    mcp: CopilotMcpConfig
    # USER-PROVIDED (not inferred): the trigger is the external event contract and triage is business routing —
    # neither is derivable from the diagram or the tools. `trigger` is a JSON Schema OR a sample event (schema
    # derived deterministically); `triage_rules` are the operator's manual predicate rules, applied verbatim.
    trigger: Dict[str, Any]
    triage_rules: List[StagedTriageRule] = Field(default_factory=list)
    # Optional per-request override of the copilot's ConfigForge model ref (else the service default
    # COPILOT_LLM_CONFIG_REF). Threaded straight into the per-ref client resolution — no code change selects a model.
    model_config_ref: Optional[str] = None


# --------------------------------------------------------------------------- #
# ADR-052 Phase 2b — the conversational refine endpoint
# --------------------------------------------------------------------------- #

class ConversationTurn(BaseModel):
    """One audit-trail entry on the session's conversation log (the design-sign-off transcript 2c renders)."""

    message: str                             # the operator's natural-language message
    reply: str                               # the copilot's plain-language reply
    needs_clarification: bool = False
    changes: List[str] = Field(default_factory=list)   # human-readable summaries of what was applied this turn


class ChangeDiff(BaseModel):
    """One before→after change on a touched element, so the reply can show exactly what moved."""

    element_id: str
    field: str                               # hitl_mode | hitl_role | capability_ref | output_name | input_map | ...
    before: Optional[Any] = None
    after: Optional[Any] = None


class CopilotChatRequest(BaseModel):
    """Body for ``POST /onboarding/{id}/copilot/chat`` — one natural-language edit at a time."""

    message: str
    # Optional per-request ConfigForge model ref (else the service default) — same contract as generate.
    model_config_ref: Optional[str] = None


class CopilotChatResponse(BaseModel):
    """The chat turn result: a plain-language reply, the concrete diffs, the refreshed report + validation, and
    the full updated session (so the caller/wizard renders the draft without a second fetch)."""

    reply: str
    changes: List[ChangeDiff] = Field(default_factory=list)
    needs_clarification: bool = False
    report: Optional[CopilotReport] = None
    validation: Optional[Dict[str, Any]] = None          # the dry-run report (findings) after this turn
    session: "OnboardingSession"


# Resolve the forward references on OnboardingSession (copilot_report, conversation) + CopilotChatResponse.
OnboardingSession.model_rebuild()
CopilotChatResponse.model_rebuild()
