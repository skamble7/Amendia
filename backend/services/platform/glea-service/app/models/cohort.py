# app/models/cohort.py
"""ADR-063 Phase 3A — cohort read-API response models (GLEA-served, observability-grade)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CohortRollup(BaseModel):
    done: int = 0
    running: int = 0
    failed: int = 0


# ADR-064 P3 — cohort SLA views (observability-grade, derived from the CohortSlaEvent stream).
class CohortSlaBreaches(BaseModel):
    external: int = 0
    amendia: int = 0
    shared: int = 0
    total: int = 0


class CohortSlaEntry(BaseModel):
    sla_id: str
    kind: str = ""                      # edge | node | end_to_end
    ref: str = ""                       # human-readable ("a->b" / "a" / "__start__->__close__")
    owner: str = ""                     # external | amendia | shared
    clock: str = ""                     # wall | business
    state: str = ""                     # at_risk | breached | satisfied | voided (current; latest event wins)
    due_at: Optional[str] = None        # emitted ISO strings (parse-free); None when absent
    at_risk_at: Optional[str] = None
    detected_at: Optional[str] = None


class CohortSlaSummary(BaseModel):
    states: List[CohortSlaEntry] = Field(default_factory=list)
    breaches: CohortSlaBreaches = Field(default_factory=CohortSlaBreaches)
    at_risk: int = 0
    satisfied: int = 0
    voided: int = 0


class CohortListEntry(BaseModel):
    cohort_instance_id: str
    cohort_def_id: str = ""
    correlation_value: str = ""
    state: str = "open"                 # open | closing | closed
    member_count: int = 0
    rollup: CohortRollup
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    outcome: Optional[str] = None       # orchestrator-reported close outcome
    anomalies: int = 0                  # count of late_join siblings
    sla_breaches: int = 0               # ADR-064 P3: total breached SLAs (current state) — compact list badge
    sla_at_risk: int = 0                # ADR-064 P3: total at-risk SLAs (current state) — compact list badge


class CohortListOut(BaseModel):
    count: int
    cohorts: List[CohortListEntry]


class CohortRosterMember(BaseModel):
    process_instance_id: str
    pack_key: str = ""
    pack_version: str = ""
    correlation_id: str = ""
    status: str = "running"             # done | running | failed (joined from the member's own audit outcome)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    outcome: Optional[str] = None
    late: bool = False                  # joined after close / cohort_def_id mismatch (a late_join anomaly)


class CohortEventOut(BaseModel):
    op: str
    at: Optional[datetime] = None
    process_instance_id: Optional[str] = None
    detail: Optional[str] = None


class CohortCloseOut(BaseModel):
    signalled: bool = False             # an external close signal arrived (state is closing/closed)
    outcome: Optional[str] = None
    state: str = "open"
    late_joins: int = 0


class CohortDetailOut(BaseModel):
    cohort_instance_id: str
    cohort_def_id: str = ""
    correlation_value: str = ""
    state: str = "open"
    member_count: int = 0
    rollup: CohortRollup
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    outcome: Optional[str] = None
    anomalies: int = 0
    roster: List[CohortRosterMember]
    events: List[CohortEventOut]
    close: CohortCloseOut
    sla: CohortSlaSummary = Field(default_factory=CohortSlaSummary)   # ADR-064 P3 (empty when no SLA events)
