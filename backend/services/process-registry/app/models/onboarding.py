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
    default_domain: str = "payment"


class BpmnInventory(BaseModel):
    """Parsed BPMN topology the downstream steps hang off of."""

    process_id: str
    bpmn_file: str
    sha256: str
    service_tasks: List[str] = Field(default_factory=list)
    user_tasks: List[str] = Field(default_factory=list)
    gateways: List[str] = Field(default_factory=list)          # exclusive gateways
    task_names: Dict[str, str] = Field(default_factory=dict)   # id -> human name (best effort)


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
    """A to-be-registered ``kind: mcp`` capability inferred from one MCP tool.

    ``input_artifact_key`` / ``output_artifact_key`` reference two ``StagedArtifact``s
    by key (same session)."""

    capability_id: str
    version: str
    title: str
    description: Optional[str] = None
    side_effect: str = "read_only"          # read_only | side_effectful
    idempotent: Optional[bool] = None
    min_hitl_mode: Optional[str] = None
    # IO — one input + one output artifact (the two inferred schemas).
    input_name: str
    input_artifact_key: str
    output_name: str
    output_artifact_key: str
    # Runtime (self-descriptive MCP, ADR-024).
    endpoint: str
    tool: str
    transport: str = "streamable_http"
    headers: Dict[str, str] = Field(default_factory=dict)
    source_tool: Optional[str] = None


class StagedBindingIO(BaseModel):
    name: str
    schema_ref: str                          # art.<...>@<range>
    required: bool = True


class StagedBinding(BaseModel):
    element_id: str
    element_kind: str                        # serviceTask | userTask
    executor_type: str                       # capability | human
    capability_ref: Optional[str] = None     # cap.<...>@<range> (serviceTask)
    role: Optional[str] = None               # role.<...>       (userTask human executor)
    assist_capability_ref: Optional[str] = None
    hitl_mode: str = "none"
    hitl_role: Optional[str] = None
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
    default_domain: str = "payment"


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


class SetCapabilitiesRequest(BaseModel):
    tools: List[CapabilityToolSelection] = Field(default_factory=list)
    reused_capability_refs: List[str] = Field(default_factory=list)


class BindingInput(BaseModel):
    element_id: str
    element_kind: str
    executor_type: str
    capability_ref: Optional[str] = None
    role: Optional[str] = None
    assist_capability_ref: Optional[str] = None
    hitl_mode: str = "none"
    hitl_role: Optional[str] = None


class SetBindingsRequest(BaseModel):
    bindings: List[BindingInput] = Field(default_factory=list)


class SetTriageRequest(BaseModel):
    triage_rules: List[StagedTriageRule] = Field(default_factory=list)


class SetPoliciesRequest(BaseModel):
    gateway_variables: List[StagedGatewayVariable] = Field(default_factory=list)
    sod_policies: List[StagedSod] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# MCP introspection request/response
# --------------------------------------------------------------------------- #

class IntrospectMcpRequest(BaseModel):
    endpoint: str
    transport: str = "streamable_http"
    headers: Dict[str, str] = Field(default_factory=dict)
    domain: str = "payment"                  # seeds suggested ids


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
