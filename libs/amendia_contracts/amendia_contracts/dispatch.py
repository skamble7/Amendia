# amendia_contracts/dispatch.py
"""Contract 4 — Dispatch event + accepted/rejected replies.

Routing keys are always built via ``EventBase.routing_key`` → ``amendia_common.events.rk``.
The runtime does not consume/publish these yet (that is the execution slice); only
the models exist here.
"""
from __future__ import annotations

from enum import Enum
from typing import ClassVar, Literal, Optional

from pydantic import Field

from amendia_common.events import (
    DISPATCH_ACCEPTED,
    DISPATCH_REJECTED,
    EXCEPTION_DISPATCHED,
    Service,
)
from amendia_contracts.common import ContractModel, EventBase


class DispatchResolution(ContractModel):
    pack_key: str
    pack_version: str = Field(..., description="Exact pinned version, resolved by registry")
    rule_id: str
    resolved_at: Optional[str] = None


class Trace(ContractModel):
    correlation_id: str = Field(
        ..., description="Stable across the exception journey; set to exception_id unless overridden"
    )
    causation_id: Optional[str] = None


class ExceptionDispatchedEvent(EventBase):
    _service: ClassVar[Service] = Service.INGESTOR
    _event_name: ClassVar[str] = EXCEPTION_DISPATCHED

    schema_version: Literal["pin.platform.exception_dispatched/1.0"] = "pin.platform.exception_dispatched/1.0"
    exception_id: str
    exception_type: str
    exception_schema_version: Optional[str] = None
    fetch_url: str
    resolution: DispatchResolution
    trace: Trace


class DispatchAcceptedEvent(EventBase):
    _service: ClassVar[Service] = Service.AGENT_RUNTIME
    _event_name: ClassVar[str] = DISPATCH_ACCEPTED

    schema_version: Literal["pin.platform.dispatch_accepted/1.0"] = "pin.platform.dispatch_accepted/1.0"
    exception_id: str
    process_instance_id: str
    pack_key: str
    pack_version: str
    trace: Trace


class DispatchRejectionReason(str, Enum):
    UNKNOWN_PACK = "unknown_pack"
    PACK_NOT_ACTIVE = "pack_not_active"
    FETCH_FAILED = "fetch_failed"
    ENVELOPE_INVALID = "envelope_invalid"
    CAPACITY = "capacity"
    # ADR-027 Phase 2.5: this runtime's execution profile is lower-ranked than the pack requires
    # (e.g. a common_subset runtime handed a pack that needs the parallel profile). Refused at load.
    PACK_REQUIRES_PROFILE = "pack_requires_profile"


class DispatchRejectedEvent(EventBase):
    _service: ClassVar[Service] = Service.AGENT_RUNTIME
    _event_name: ClassVar[str] = DISPATCH_REJECTED

    schema_version: Literal["pin.platform.dispatch_rejected/1.0"] = "pin.platform.dispatch_rejected/1.0"
    exception_id: str
    reason: DispatchRejectionReason
    detail: str
    trace: Trace
