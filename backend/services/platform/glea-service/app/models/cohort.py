# app/models/cohort.py
"""ADR-063 Phase 3A — cohort read-API response models (GLEA-served, observability-grade)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class CohortRollup(BaseModel):
    done: int = 0
    running: int = 0
    failed: int = 0


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
