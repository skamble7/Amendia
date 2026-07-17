# amendia_contracts/process_pack.py
"""Contract 1 — ProcessPack manifest.

Faithful Pydantic v2 implementation of the ProcessPackManifest JSON Schema in
the contracts doc §1. Cross-document checks (capability-exists, schema-compat,
BPMN parse) are NOT done here — they belong to the registry/onboarding step.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Literal, Optional, Union

from pydantic import Field, field_validator, model_validator

from amendia_contracts.common import (
    ArtifactBareRef,
    ArtifactRef,
    CapabilityRef,
    ContractModel,
    HitlMode,
    PackKey,
    RoleId,
    SemVerStr,
    Sha256Hex,
    TimestampsMixin,
)

# --------------------------------------------------------------------------- #
# Triage predicate — recursive tagged union over envelope fields
# --------------------------------------------------------------------------- #

class LeafOp(str, Enum):
    EQ = "eq"
    NE = "ne"
    IN = "in"
    STARTS_WITH = "starts_with"
    INTERSECTS = "intersects"
    EXISTS = "exists"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"


class AllPredicate(ContractModel):
    all: List["Predicate"] = Field(..., min_length=1)


class AnyPredicate(ContractModel):
    any: List["Predicate"] = Field(..., min_length=1)


class NotPredicate(ContractModel):
    # `not` is a Python keyword → store as not_, serialize/accept as "not".
    not_: "Predicate" = Field(..., alias="not")


class LeafPredicate(ContractModel):
    field: str
    op: LeafOp
    value: object = None


# Smart union: each branch has disjoint required keys and forbids extras, so the
# present key unambiguously selects the member.
Predicate = Union[AllPredicate, AnyPredicate, NotPredicate, LeafPredicate]

AllPredicate.model_rebuild()
AnyPredicate.model_rebuild()
NotPredicate.model_rebuild()


class TriageRule(ContractModel):
    rule_id: str
    priority: int = Field(..., description="Lower number wins when multiple packs match")
    description: Optional[str] = None
    when: Predicate


# --------------------------------------------------------------------------- #
# Bindings
# --------------------------------------------------------------------------- #

class CapabilityExecutor(ContractModel):
    type: Literal["capability"]
    capability: CapabilityRef


class HumanExecutor(ContractModel):
    type: Literal["human"]
    role: RoleId
    assist_capability: Optional[CapabilityRef] = None


class MessageExecutor(ContractModel):
    """ADR-031 (Phase 2.4): the "executor" of a message catch / receive element is the external
    world. ``message_name`` is the business message this element awaits; correlation is by business
    anchor (exception_id / correlation_id) + this name — no per-pack correlation expressions."""

    type: Literal["message"]
    message_name: str


Executor = Union[CapabilityExecutor, HumanExecutor, MessageExecutor]

# element kinds that bind a MessageExecutor (no capability, no HITL).
_MESSAGE_KINDS = ("messageCatch", "receiveTask")


class Hitl(ContractModel):
    mode: HitlMode
    role: Optional[RoleId] = None

    @model_validator(mode="after")
    def _role_required_unless_none(self) -> "Hitl":
        if self.mode is not HitlMode.NONE and self.role is None:
            raise ValueError(f"hitl.role is required for mode '{self.mode.value}'")
        return self


class ArtifactIO(ContractModel):
    name: str
    schema_: ArtifactRef = Field(..., alias="schema")
    required: bool = True


class Binding(ContractModel):
    element_id: str
    # ADR-033 (Phase 2.7): the full standard BPMN task set (each routes to an executor category).
    element_kind: Literal[
        "serviceTask", "userTask", "messageCatch", "receiveTask",
        "sendTask", "scriptTask", "manualTask", "businessRuleTask",
    ]
    executor: Executor = Field(..., discriminator="type")
    # HITL is required for capability/human executors; a message element has no human gate (ADR-031).
    hitl: Optional[Hitl] = None
    inputs: List[ArtifactIO] = Field(default_factory=list)
    # A message binding's outputs are OPTIONAL: if declared, the delivered payload validates against
    # the pinned artifact schema and commits as that artifact; if absent, the message is a pure signal.
    outputs: List[ArtifactIO] = Field(default_factory=list)

    @model_validator(mode="after")
    def _executor_matches_kind(self) -> "Binding":
        etype = self.executor.type
        if etype == "message":
            if self.element_kind not in _MESSAGE_KINDS:
                raise ValueError(f"message executor requires element_kind in {_MESSAGE_KINDS}, "
                                 f"got '{self.element_kind}'")
        else:
            if self.element_kind in _MESSAGE_KINDS:
                raise ValueError(f"element_kind '{self.element_kind}' requires a message executor")
            if self.hitl is None:
                raise ValueError(f"hitl is required for a '{etype}' executor binding")
        return self


# --------------------------------------------------------------------------- #
# Other manifest sub-objects
# --------------------------------------------------------------------------- #

class ProcessRef(ContractModel):
    bpmn_file: str
    process_id: str
    bpmn_sha256: Sha256Hex


class RequiresCapability(ContractModel):
    ref: CapabilityRef
    resolved: Optional[CapabilityRef] = Field(
        default=None, description="Pinned by the registry at activation; absent while draft"
    )

    @field_validator("resolved")
    @classmethod
    def _resolved_must_be_pinned(cls, v: Optional[CapabilityRef]) -> Optional[CapabilityRef]:
        if v is not None and not v.is_pinned:
            raise ValueError(f"resolved ref must be pinned to an exact version, got '{v}'")
        return v


class GatewayVariable(ContractModel):
    gateway_id: str
    variable: str = Field(..., description="e.g. beneficiary.repair_verdict")
    source_artifact: ArtifactBareRef


class SeparationOfDuties(ContractModel):
    constraint: Literal["distinct_actor"]
    elements: List[str] = Field(..., min_length=2)


class Policies(ContractModel):
    separation_of_duties: Optional[List[SeparationOfDuties]] = None


class PackStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #

class ProcessPackManifest(ContractModel, TimestampsMixin):
    manifest_version: Literal["1.0"]
    pack_key: PackKey
    version: SemVerStr
    title: str
    description: Optional[str] = None
    process: ProcessRef
    triage_rules: List[TriageRule] = Field(..., min_length=1)
    requires_capabilities: List[RequiresCapability]
    artifacts: List[ArtifactRef]
    bindings: List[Binding] = Field(..., min_length=1)
    gateway_variables: Optional[List[GatewayVariable]] = None
    policies: Optional[Policies] = None
    # ADR-021 — explicit, per-capability justification for a *side-effectful* deep_agent
    # (keyed by capability_id). The registry refuses a side-effectful autonomous loop unless
    # justified here. Additive; empty for every existing pack.
    deep_agent_justifications: Dict[str, str] = Field(default_factory=dict)
    status: PackStatus
    created_by: Optional[str] = None
