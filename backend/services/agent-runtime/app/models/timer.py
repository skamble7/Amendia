# app/models/timer.py
"""Durable timer record (ADR-027 Phase 2.2) — the runtime-owned scheduler substrate.

One row per pending timer. A timer intermediate-catch parks the instance for a duration
(``kind="intermediate"``); an interrupting SLA boundary on a HITL gate escalates on breach
(``kind="boundary"``). Timers are durable so the poller re-fires anything due after a restart —
there is no delayed-message broker or external scheduler. The unique ``(process_instance_id,
element_id, kind)`` index makes re-registration (crash replay re-entering the node) idempotent.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import Field

from app.models.common import ContractModel, utcnow


class TimerKind(str, Enum):
    INTERMEDIATE = "intermediate"   # timer intermediate-catch event — park then auto-proceed
    BOUNDARY = "boundary"           # interrupting SLA boundary on a HITL gate — escalate on breach


class TimerStatus(str, Enum):
    PENDING = "pending"
    FIRED = "fired"
    CANCELLED = "cancelled"


class Timer(ContractModel):
    timer_id: str
    process_instance_id: str
    element_id: str                 # the catch event id, or the HITL gate host id (boundary)
    kind: TimerKind
    fire_at: datetime
    status: TimerStatus = TimerStatus.PENDING
    # The LangGraph interrupt id to resume when this fires (the instance is parked at that interrupt).
    interrupt_id: Optional[str] = None
    # boundary only: the HITL task to expire when the SLA breaches (the human loses the race).
    task_id: Optional[str] = None
    # ADR-031 Phase 2.4: set when this timer is a timer *arm* of an event-based gateway — the instance
    # parks WAITING_MESSAGE (not WAITING_TIMER), and firing cancels the sibling message arms.
    gateway_id: Optional[str] = None
    pack_key: Optional[str] = None
    pack_version: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
