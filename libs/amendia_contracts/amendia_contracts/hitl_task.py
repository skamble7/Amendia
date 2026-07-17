# amendia_contracts/hitl_task.py
"""Contract 5 — HITL task / approval model + thin HITL events.

Self-contained invariants enforced here: a decided task must carry a decision, and
that decision must be one of the task's allowed_decisions. Claim/SoD enforcement and
decision→graph routing are runtime behaviour (later), not model validation.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, Dict, List, Literal, Optional

from pydantic import Field, StringConstraints, model_validator
from typing_extensions import Annotated

from amendia_common.events import (
    HITL_TASK_CREATED,
    HITL_TASK_DECIDED,
    HITL_TASK_EXPIRED,
    Service,
)
from amendia_contracts.common import (
    ContractModel,
    EventBase,
    PackKey,
    RoleId,
    SemVerStr,
    TimestampsMixin,
)

# Pinned artifact ref (e.g. art.payment.repair_verdict@1.0.0) for review snapshots.
PinnedArtifactRefStr = Annotated[str, StringConstraints(pattern=r"^art\..+@\d+\.\d+\.\d+$")]


class HitlTaskMode(str, Enum):
    REVIEW_AFTER = "review_after"
    APPROVE_RESULT = "approve_result"
    APPROVE_ACTIONS = "approve_actions"
    MANUAL = "manual"


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class Decision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT_AND_APPROVE = "edit_and_approve"
    RETURN_FOR_REWORK = "return_for_rework"
    COMPLETE = "complete"
    ESCALATE = "escalate"


class TaskStatus(str, Enum):
    OPEN = "open"
    CLAIMED = "claimed"
    DECIDED = "decided"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PayloadArtifact(ContractModel):
    name: str
    schema_: PinnedArtifactRefStr = Field(..., alias="schema")
    data: Dict[str, Any]


class ProposedAction(ContractModel):
    action_id: str
    kind: str = Field(..., description="e.g. release_payment, send_pacs004, send_camt029")
    summary: str
    detail: Dict[str, Any]


class TaskPayload(ContractModel):
    artifacts: Optional[List[PayloadArtifact]] = None
    proposed_actions: Optional[List[ProposedAction]] = None
    context_url: Optional[str] = None


class Sod(ContractModel):
    excluded_users: Optional[List[str]] = None
    derived_from: Optional[List[str]] = None


class DecisionRecord(ContractModel):
    decision: Decision
    decided_by: str
    decided_at: datetime
    comment: Optional[str] = None
    edits: Optional[Dict[str, Any]] = None
    approved_action_ids: Optional[List[str]] = None


class HitlTask(ContractModel, TimestampsMixin):
    task_id: str
    process_instance_id: str
    pack_key: PackKey
    pack_version: SemVerStr
    element_id: str
    exception_id: str
    hitl_mode: HitlTaskMode
    role: RoleId
    title: str
    description: Optional[str] = None
    priority: TaskPriority = TaskPriority.NORMAL
    due_at: Optional[datetime] = None
    assignee: Optional[str] = None
    sod: Optional[Sod] = None
    payload: TaskPayload
    allowed_decisions: List[Decision] = Field(..., min_length=1)
    status: TaskStatus
    decision: Optional[DecisionRecord] = None
    # ADR-027 Phase 2.1: the LangGraph interrupt id this task corresponds to. Required to resume
    # exactly this gate when a parallel superstep raises several concurrent interrupts (they must
    # be resolved one at a time via ``Command(resume={id: decision})``). Absent for legacy tasks.
    interrupt_id: Optional[str] = None

    @model_validator(mode="after")
    def _decided_requires_valid_decision(self) -> "HitlTask":
        if self.status is TaskStatus.DECIDED:
            if self.decision is None:
                raise ValueError("a decided task must include a decision")
            if self.decision.decision not in self.allowed_decisions:
                raise ValueError(
                    f"decision '{self.decision.decision.value}' is not in allowed_decisions"
                )
        return self


# --------------------------------------------------------------------------- #
# Thin HITL events (fanned out to the UI by the notification service)
# --------------------------------------------------------------------------- #

class HitlTaskCreatedEvent(EventBase):
    _service: ClassVar[Service] = Service.AGENT_RUNTIME
    _event_name: ClassVar[str] = HITL_TASK_CREATED

    schema_version: Literal["pin.platform.hitl_task_created/1.0"] = "pin.platform.hitl_task_created/1.0"
    task_id: str
    exception_id: str
    process_instance_id: str
    element_id: str
    role: RoleId


class HitlTaskDecidedEvent(EventBase):
    _service: ClassVar[Service] = Service.AGENT_RUNTIME
    _event_name: ClassVar[str] = HITL_TASK_DECIDED

    schema_version: Literal["pin.platform.hitl_task_decided/1.0"] = "pin.platform.hitl_task_decided/1.0"
    task_id: str
    exception_id: str
    process_instance_id: str
    element_id: str
    role: RoleId
    decision: Decision
    decided_by: str


class HitlTaskExpiredEvent(EventBase):
    """ADR-027 Phase 2.2: a HITL gate breached its SLA and was escalated via its timer boundary
    event. The task is now ``expired``; the process routed to the boundary's escalation target."""

    _service: ClassVar[Service] = Service.AGENT_RUNTIME
    _event_name: ClassVar[str] = HITL_TASK_EXPIRED

    schema_version: Literal["pin.platform.hitl_task_expired/1.0"] = "pin.platform.hitl_task_expired/1.0"
    task_id: str
    exception_id: str
    process_instance_id: str
    element_id: str
    role: RoleId
    escalated_to: Optional[str] = None   # the boundary's escalation target element id
