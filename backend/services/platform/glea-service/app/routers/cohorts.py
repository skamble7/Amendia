# app/routers/cohorts.py
"""ADR-063 Phase 3A — cohort read API (GLEA-served, event-sourced from the CohortLifecycleEvent stream).

Observability-grade: derived from the fail-soft event stream, not the authoritative agent-runtime SoR. Member
status/rollup are joined from the members' own audit_events outcomes."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.clickhouse.client import StorageUnavailable
from app.clickhouse.reader import CohortReader
from app.deps import get_cohort_reader
from app.models.cohort import CohortDetailOut, CohortListOut
from app.readmodels import build_cohort_detail, build_cohort_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cohorts", tags=["cohorts"])


def _member_cids(rows: List[Dict[str, Any]]) -> List[str]:
    return sorted({r.get("member_correlation_id") for r in rows if r.get("member_correlation_id")})


@router.get("", response_model=CohortListOut)
async def list_cohorts(
    state: Optional[str] = Query(None, description="filter by state: open | closing | closed"),
    reader: CohortReader = Depends(get_cohort_reader),
):
    """All cohorts (newest opened first), each with member_count + a done/running/failed rollup."""
    try:
        rows = await reader.cohort_events_all()
        outcomes = await reader.member_outcomes(_member_cids(rows))
    except StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="cohort store unavailable") from exc
    cohorts = build_cohort_list(rows, outcomes)
    if state:
        cohorts = [c for c in cohorts if c["state"] == state]
    return CohortListOut(count=len(cohorts), cohorts=cohorts)


@router.get("/by-correlation/{correlation_value}", response_model=CohortDetailOut)
async def cohort_by_correlation(correlation_value: str, reader: CohortReader = Depends(get_cohort_reader)):
    """Detail resolved by the external business key (the cohort's sole handle)."""
    try:
        rows = await reader.cohort_events_by_correlation_value(correlation_value)
        detail = build_cohort_detail(rows, await reader.member_outcomes(_member_cids(rows)))
    except StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="cohort store unavailable") from exc
    if detail is None:
        raise HTTPException(status_code=404, detail=f"no cohort for correlation_value '{correlation_value}'")
    return detail


@router.get("/{cohort_instance_id}", response_model=CohortDetailOut)
async def cohort_detail(cohort_instance_id: str, reader: CohortReader = Depends(get_cohort_reader)):
    """Identity + roster (each member's joined status/duration/outcome) + lifecycle stream + close summary."""
    try:
        rows = await reader.cohort_events_for(cohort_instance_id)
        detail = build_cohort_detail(rows, await reader.member_outcomes(_member_cids(rows)))
    except StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="cohort store unavailable") from exc
    if detail is None:
        raise HTTPException(status_code=404, detail=f"unknown cohort '{cohort_instance_id}'")
    return detail
