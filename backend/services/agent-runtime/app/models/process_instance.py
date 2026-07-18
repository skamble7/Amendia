# app/models/process_instance.py
"""Runtime-owned aggregate (NOT in the contracts doc).

Minimal now because dispatch replies reference ``process_instance_id``. No graph/
checkpoint fields yet — those arrive with the execution slice. The idempotency key
is derived from (exception_id, pack_key, pack_version) so a duplicate dispatch maps
to the existing instance rather than starting a second one.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import Field

from app.models.common import ContractModel, PackKey, SemVerStr, utcnow


class InstanceStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_HITL = "waiting_hitl"
    # ADR-027 Phase 2.2: parked on a timer intermediate-catch event, waiting for a duration to
    # elapse. Like WAITING_HITL it is a durable, crash-safe park (no thread running) — the timer
    # poller resumes it when the timer fires; the startup recovery sweep leaves it alone.
    WAITING_TIMER = "waiting_timer"
    # ADR-031 Phase 2.4: parked on a message catch / receive task / event-based gateway, waiting for
    # a correlated inbound business message (delivered via POST /messages). Durable + crash-safe like
    # the others; the recovery sweep leaves it alone — a delivery resumes it.
    WAITING_MESSAGE = "waiting_message"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def compute_idempotency_key(exception_id: str, pack_key: str, pack_version: str) -> str:
    """Deterministic key: a duplicate dispatch resolves to the same instance."""
    return f"{exception_id}:{pack_key}:{pack_version}"


class ProcessInstance(ContractModel):
    process_instance_id: str
    exception_id: str
    pack_key: PackKey
    pack_version: SemVerStr
    status: InstanceStatus = InstanceStatus.CREATED
    correlation_id: str
    idempotency_key: str
    # Execution fields (LangGraph thread == process_instance_id).
    outcome: Optional[str] = None
    last_error: Optional[str] = None
    artifact_names: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @classmethod
    def new(
        cls,
        *,
        process_instance_id: str,
        exception_id: str,
        pack_key: str,
        pack_version: str,
        correlation_id: str | None = None,
        status: InstanceStatus = InstanceStatus.CREATED,
    ) -> "ProcessInstance":
        return cls(
            process_instance_id=process_instance_id,
            exception_id=exception_id,
            pack_key=pack_key,
            pack_version=pack_version,
            status=status,
            correlation_id=correlation_id or exception_id,
            idempotency_key=compute_idempotency_key(exception_id, pack_key, pack_version),
        )
