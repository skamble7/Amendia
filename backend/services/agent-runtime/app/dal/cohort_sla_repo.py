# app/dal/cohort_sla_repo.py
"""ADR-064 Phase 2 — repositories for the cohort SLA substrate (sibling of the ADR-027 timer repo).

Both mirror the ADR-027 idempotent-register + guarded-CAS discipline so crash replay never duplicates and
firing is exactly-once:

* :class:`CohortSlaExpectationRepository` — the per-expectation SoR. ``register`` is idempotent (``$setOnInsert``
  on the unique (cohort_instance_id, sla_id)); ``transition`` is a guarded compare-and-set on ``state`` (the
  once-only guard the satisfy/void/fire paths race on — exactly one terminal transition wins).
* :class:`CohortSlaTimerRepository` — the durable fire schedule. ``fire_at`` is stored native (not the JSON
  string) so the ``$lte`` due-scan is a real temporal comparison, exactly like ``timer_repo``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument

from app.models.cohort_sla import (
    CohortSlaExpectation, CohortSlaTimer, SlaExpectationState, SlaTimerStatus,
)
from app.models.common import utcnow

_PROJECTION = {"_id": 0}


class CohortSlaExpectationRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def register(self, exp: CohortSlaExpectation) -> CohortSlaExpectation:
        """Idempotent register: insert if absent, else leave the existing expectation untouched (a crash-
        replay re-schedule must not move ``due_at`` or resurrect a resolved expectation)."""
        key = {"cohort_instance_id": exp.cohort_instance_id, "sla_id": exp.sla_id}
        await self._coll.update_one(key, {"$setOnInsert": _store_doc(exp)}, upsert=True)
        stored = await self._coll.find_one(key, projection=_PROJECTION)
        return CohortSlaExpectation.model_validate(stored)

    async def get(self, cohort_instance_id: str, sla_id: str) -> Optional[CohortSlaExpectation]:
        doc = await self._coll.find_one(
            {"cohort_instance_id": cohort_instance_id, "sla_id": sla_id}, projection=_PROJECTION)
        return CohortSlaExpectation.model_validate(doc) if doc else None

    async def list_for_cohort(self, cohort_instance_id: str) -> List[CohortSlaExpectation]:
        cursor = self._coll.find({"cohort_instance_id": cohort_instance_id}, projection=_PROJECTION)
        return [CohortSlaExpectation.model_validate(d) async for d in cursor]

    async def transition(
        self, cohort_instance_id: str, sla_id: str, *,
        expected: List[SlaExpectationState], new_state: SlaExpectationState,
        stamps: Optional[Dict[str, Any]] = None,
    ) -> Optional[CohortSlaExpectation]:
        """Guarded CAS ``state ∈ expected → new_state`` (+ optional timestamp stamps). Returns the updated
        expectation, or None when the guard didn't match (another path already resolved it) — the once-only
        gate that makes satisfy/void/at_risk/breach exactly-once."""
        update: Dict[str, Any] = {"state": new_state.value, "updated_at": _iso(utcnow())}
        for k, v in (stamps or {}).items():
            update[k] = v.isoformat() if isinstance(v, datetime) else v
        doc = await self._coll.find_one_and_update(
            {"cohort_instance_id": cohort_instance_id, "sla_id": sla_id,
             "state": {"$in": [s.value for s in expected]}},
            {"$set": update},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        doc.pop("_id", None)
        return CohortSlaExpectation.model_validate(doc)

    async def mark_arrived_late(self, cohort_instance_id: str, sla_id: str) -> None:
        """Record that a satisfy/void landed AFTER a breach fired — attribution keeps the truth, the breach
        stands (``state`` is never changed here)."""
        await self._coll.update_one(
            {"cohort_instance_id": cohort_instance_id, "sla_id": sla_id},
            {"$set": {"arrived_late": True, "updated_at": _iso(utcnow())}},
        )


class CohortSlaTimerRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def register(self, timer: CohortSlaTimer) -> CohortSlaTimer:
        """Idempotent register keyed on the unique (cohort_instance_id, sla_id, phase)."""
        key = {"cohort_instance_id": timer.cohort_instance_id, "sla_id": timer.sla_id,
               "phase": timer.phase.value}
        await self._coll.update_one(key, {"$setOnInsert": _store_timer(timer)}, upsert=True)
        stored = await self._coll.find_one(key, projection=_PROJECTION)
        return CohortSlaTimer.model_validate(stored)

    async def due(self, now: datetime, *, limit: int = 500) -> List[CohortSlaTimer]:
        """Pending timers whose ``fire_at`` has arrived (``<= now``)."""
        cursor = self._coll.find(
            {"status": SlaTimerStatus.PENDING.value, "fire_at": {"$lte": now}},
            projection=_PROJECTION,
        ).limit(limit)
        return [CohortSlaTimer.model_validate(d) async for d in cursor]

    async def mark(self, sla_timer_id: str, status: SlaTimerStatus) -> Optional[CohortSlaTimer]:
        """Guarded pending → ``status``. Returns None if it was not pending (already resolved) — the
        once-only guard so a re-fired-after-restart poller (or two poller ticks) fire each row once."""
        doc = await self._coll.find_one_and_update(
            {"sla_timer_id": sla_timer_id, "status": SlaTimerStatus.PENDING.value},
            {"$set": {"status": status.value, "updated_at": _iso(utcnow())}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        doc.pop("_id", None)
        return CohortSlaTimer.model_validate(doc)

    async def cancel_for_expectation(self, cohort_instance_id: str, sla_id: str) -> int:
        """Cancel the pending timer rows of one expectation (cancel-on-satisfy / void)."""
        res = await self._coll.update_many(
            {"cohort_instance_id": cohort_instance_id, "sla_id": sla_id,
             "status": SlaTimerStatus.PENDING.value},
            {"$set": {"status": SlaTimerStatus.CANCELLED.value, "updated_at": _iso(utcnow())}},
        )
        return res.modified_count

    async def list_for_cohort(self, cohort_instance_id: str) -> List[CohortSlaTimer]:
        cursor = self._coll.find({"cohort_instance_id": cohort_instance_id}, projection=_PROJECTION)
        return [CohortSlaTimer.model_validate(d) async for d in cursor]


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _store_doc(exp: CohortSlaExpectation) -> dict:
    """Persisted expectation: JSON dump, but the temporal fields stay native for correct ordering/reads."""
    doc = exp.to_doc()
    for f in ("anchor_at", "due_at", "at_risk_at"):
        val = getattr(exp, f)
        if val is not None:
            doc[f] = val
    return doc


def _store_timer(timer: CohortSlaTimer) -> dict:
    """Persisted timer: ``fire_at`` native for the ``$lte`` due-scan (mirrors ``timer_repo``)."""
    doc = timer.to_doc()
    doc["fire_at"] = timer.fire_at
    return doc
