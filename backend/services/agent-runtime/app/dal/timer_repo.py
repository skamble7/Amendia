# app/dal/timer_repo.py
"""Durable timer repository (ADR-027 Phase 2.2).

Registration is idempotent (upsert keyed on the unique ``(instance, element, kind)`` index via
``$setOnInsert``) so re-entering a node on crash replay never duplicates or moves a pending timer.
``fire_at`` is stored as a native datetime (not the JSON-dumped string) so the ``$lte`` due-scan is a
real temporal comparison — Mongo/mongomock normalize to UTC — rather than a fragile lexical one.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument

from app.models.common import utcnow
from app.models.timer import Timer, TimerStatus

_PROJECTION = {"_id": 0}


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _store_doc(timer: Timer) -> dict:
    """The persisted shape: JSON dump, but with ``fire_at`` kept as a native datetime for correct
    ``$lte`` comparison in the due-scan."""
    doc = timer.to_doc()
    doc["fire_at"] = timer.fire_at
    return doc


class TimerRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def register(self, timer: Timer) -> Timer:
        """Idempotent register: insert if absent, else leave the existing pending timer untouched
        (a crash-replay re-entry must not move ``fire_at`` or resurrect a resolved timer)."""
        key = {
            "process_instance_id": timer.process_instance_id,
            "element_id": timer.element_id,
            "kind": timer.kind.value,
        }
        await self._coll.update_one(key, {"$setOnInsert": _store_doc(timer)}, upsert=True)
        stored = await self._coll.find_one(key, projection=_PROJECTION)
        return Timer.model_validate(stored)

    async def get(self, timer_id: str) -> Optional[Timer]:
        doc = await self._coll.find_one({"timer_id": timer_id}, projection=_PROJECTION)
        return Timer.model_validate(doc) if doc else None

    async def due(self, now: datetime, *, limit: int = 200) -> List[Timer]:
        """Pending timers whose ``fire_at`` has arrived (``<= now``)."""
        cursor = self._coll.find(
            {"status": TimerStatus.PENDING.value, "fire_at": {"$lte": now}},
            projection=_PROJECTION,
        ).limit(limit)
        return [Timer.model_validate(d) async for d in cursor]

    async def mark(self, timer_id: str, status: TimerStatus) -> Optional[Timer]:
        """Guarded pending → ``status`` transition (fired/cancelled). Returns None if it was not
        pending (already resolved) — this is the once-only guard for the poller."""
        doc = await self._coll.find_one_and_update(
            {"timer_id": timer_id, "status": TimerStatus.PENDING.value},
            {"$set": {"status": status.value, "updated_at": _iso(utcnow())}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        doc.pop("_id", None)
        return Timer.model_validate(doc)

    async def cancel_by_interrupt(self, process_instance_id: str, interrupt_id: Optional[str]) -> int:
        """Cancel the pending timer(s) for this instance's interrupt — the human won the race, so the
        SLA escalation must not fire. No-op when ``interrupt_id`` is None (legacy)."""
        if interrupt_id is None:
            return 0
        res = await self._coll.update_many(
            {"process_instance_id": process_instance_id, "interrupt_id": interrupt_id,
             "status": TimerStatus.PENDING.value},
            {"$set": {"status": TimerStatus.CANCELLED.value, "updated_at": _iso(utcnow())}},
        )
        return res.modified_count

    async def cancel_for_instance(self, process_instance_id: str) -> int:
        res = await self._coll.update_many(
            {"process_instance_id": process_instance_id, "status": TimerStatus.PENDING.value},
            {"$set": {"status": TimerStatus.CANCELLED.value, "updated_at": _iso(utcnow())}},
        )
        return res.modified_count

    async def cancel_gateway_arms(self, process_instance_id: str, *, keep_element_id: str) -> int:
        """ADR-031: cancel the losing timer arm(s) of an event-based gateway after another arm won."""
        res = await self._coll.update_many(
            {"process_instance_id": process_instance_id, "status": TimerStatus.PENDING.value,
             "gateway_id": {"$ne": None}, "element_id": {"$ne": keep_element_id}},
            {"$set": {"status": TimerStatus.CANCELLED.value, "updated_at": _iso(utcnow())}},
        )
        return res.modified_count

    async def list_for_instance(self, process_instance_id: str) -> List[Timer]:
        cursor = self._coll.find({"process_instance_id": process_instance_id}, projection=_PROJECTION)
        return [Timer.model_validate(d) async for d in cursor]
