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


class SetBindingsRequest(BaseModel):
    bindings: List[BindingInput] = Field(default_factory=list)


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


class IntrospectMcpResponse(BaseModel):
    endpoint: str
    transport: str
    tools: List[IntrospectedTool] = Field(default_factory=list)
