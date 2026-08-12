# app/models/cohort_sla.py
"""ADR-064 Phase 2 — the runtime SLA substrate (a SIBLING of the ADR-027 timer, not an overload).

Two persisted shapes, both cohort-scoped (never keyed by a process instance / LangGraph interrupt):

* :class:`CohortSlaExpectation` — the per-expectation SoR (``pending → at_risk → satisfied|voided|breached``).
  One row per (cohort_instance_id, sla_id). This is the authoritative record P3's read-model + P4's UI read
  over REST. It carries everything the fire path + P3 need without re-reading the cohort (owner/clock/times +
  the matching keys ``satisfy_node``/``satisfy_moment``/``split`` derived from the snapshot at schedule time).
* :class:`CohortSlaTimer` — the durable fire schedule. One row per (cohort_instance_id, sla_id, phase). A
  ``breach`` row at ``anchor + deadline`` always; an ``at_risk`` row at ``anchor + at_risk`` when a lead is set.
  Durable so the poller re-fires anything overdue after a restart (late-but-never-missed).

Why a sibling and not the instance ``Timer``: an SLA timer's fire-action *evaluates cohort state and flags* —
it never resumes a parked LangGraph interrupt. Sharing the instance timer collection/poller would entangle the
interrupt-resuming fire path with an evaluate-only one. Same ADR-027 shapes (durable rows, ``due(now)``,
guarded CAS ``mark``, injectable ``now``) — separate substrate.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import Field

from app.models.common import ContractModel, utcnow


class SlaExpectationKind(str, Enum):
    EDGE = "edge"              # a precedence hop (after anchor of `from`, expect `to`)
    NODE = "node"             # a segment's arrival → completion runtime promise
    END_TO_END = "end_to_end" # cohort open → close


class SlaExpectationState(str, Enum):
    PENDING = "pending"        # scheduled, awaiting its satisfying event
    AT_RISK = "at_risk"        # crossed the at-risk lead, still outstanding (amber)
    SATISFIED = "satisfied"    # the satisfying event arrived in time
    VOIDED = "voided"          # excused (XOR sibling arrived / cohort closed) — never a fault
    BREACHED = "breached"      # deadline passed unmet — recorded + attributed


class SlaMoment(str, Enum):
    """The observable moment that SATISFIES an expectation (the anchor side is captured by *when* we schedule)."""
    ARRIVAL = "arrival"        # a member spawned (join_on_spawn) for the satisfy node
    COMPLETION = "completion"  # a member reached terminal for the satisfy node
    CLOSE = "close"            # the external close message arrived (satisfies the end-to-end expectation)


class SlaTimerPhase(str, Enum):
    AT_RISK = "at_risk"
    BREACH = "breach"


class SlaTimerStatus(str, Enum):
    PENDING = "pending"
    FIRED = "fired"
    CANCELLED = "cancelled"


class CohortSlaExpectation(ContractModel):
    """Per-expectation SoR row (one per (cohort_instance_id, sla_id))."""
    sla_id: str                                    # stable per-cohort id ("edge:a->b" / "node:a" / "e2e")
    cohort_instance_id: str
    cohort_def_id: str                             # denormalised so the fire path + P3 read it without a join
    correlation_value: str                         # denormalised (structural — opaque business key)
    kind: SlaExpectationKind
    ref: str                                       # human-readable ("a->b" / "a" / "start->close")
    owner: str                                     # external | amendia | shared
    clock: str                                     # wall | business
    # Matching keys (from the snapshot, forward-only): what event resolves this expectation.
    satisfy_node: str                              # the node whose moment satisfies (or __close__ for e2e)
    satisfy_moment: SlaMoment
    split: Optional[str] = None                    # the edge's split (and|xor) — drives XOR-sibling voiding
    from_node: Optional[str] = None                # edge source (for XOR-sibling lookup)
    state: SlaExpectationState = SlaExpectationState.PENDING
    anchor_at: datetime                            # when the clock started
    due_at: datetime                               # scheduled breach instant (clock-adjusted)
    at_risk_at: Optional[datetime] = None          # scheduled at-risk instant (clock-adjusted), if a lead is set
    at_risk_marked_at: Optional[datetime] = None   # when at_risk actually fired
    satisfied_at: Optional[datetime] = None
    voided_at: Optional[datetime] = None
    breached_at: Optional[datetime] = None
    detected_at: Optional[datetime] = None         # wall-now at the terminal transition (> due_at if late)
    arrived_late: bool = False                     # a satisfy/void that landed AFTER a breach fired (truth kept)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CohortSlaTimer(ContractModel):
    """Durable fire schedule (one per (cohort_instance_id, sla_id, phase))."""
    sla_timer_id: str
    cohort_instance_id: str
    sla_id: str
    phase: SlaTimerPhase
    fire_at: datetime
    status: SlaTimerStatus = SlaTimerStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
