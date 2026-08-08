# app/models/cohort_instance.py
"""ADR-063 Phase 1 — the cohort-instance system-of-record (runtime-owned aggregate).

A cohort instance is a **purely observational** grouping of the segment instances (members) that share one
real-world case, identified and deduplicated by ``correlation_value`` alone (a globally-unique V1 invariant,
enforced by a unique index). It is a persisted state machine: ``open → closing → closed`` (only ``open`` and
member accumulation are exercised in Phase 1; ``closing``/``closed`` land with the close ingress in Phase 2).
It has **zero execution authority** — it never sequences, gates, or terminates any member.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import Field

from app.models.common import ContractModel, utcnow


class CohortState(str, Enum):
    OPEN = "open"        # created when its first member spawned; members accumulate
    CLOSING = "closing"  # external close signal arrived while ≥1 member still running (Phase 2)
    CLOSED = "closed"    # terminal — no member in flight (Phase 2)


class CohortMember(ContractModel):
    """One segment instance in a cohort's roster. ``terminal`` is the drain marker flipped when the member
    reaches a terminal state (Phase 1 wires this; Phase 2's close path consumes ``active_member_count``)."""
    process_instance_id: str
    pack_key: str
    terminal: bool = False


class CohortInstance(ContractModel):
    cohort_instance_id: str
    cohort_def_id: str
    correlation_value: str
    state: CohortState = CohortState.OPEN
    members: List[CohortMember] = Field(default_factory=list)
    # Count of members not yet terminal. Maintained atomically by the repo (add_member $inc +1;
    # mark_member_terminal $inc -1) so the Phase-2 drain can transition closing → closed when it hits 0.
    active_member_count: int = 0
    opened_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    closed_at: Optional[datetime] = None
    close_outcome: Optional[str] = None
