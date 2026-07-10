# app/dal/ingestion_repo.py
"""Data-access layer for ingestion-log records — CRUD over Mongo, no business logic."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.models.ingestion import (
    EventRef,
    IngestionRecord,
    IngestionStatus,
    StatusChange,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IngestionRepository:
    """Async repository over the ingestions collection."""

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def create_received(
        self,
        *,
        exception_id: str,
        exception_type: str,
        event: EventRef,
        detail: Optional[Dict[str, Any]],
        fetch_error: Optional[str] = None,
    ) -> Optional[IngestionRecord]:
        """Insert a new record in the ``received`` state.

        Returns the created record, or ``None`` if one already exists for this
        ``exception_id`` (idempotent no-op for redelivery).
        """
        now = _utcnow()
        record = IngestionRecord(
            exception_id=exception_id,
            exception_type=exception_type,
            event=event,
            exception_detail=detail,
            fetch_error=fetch_error,
            status=IngestionStatus.RECEIVED,
            status_history=[StatusChange(status=IngestionStatus.RECEIVED, at=now)],
            created_at=now,
            updated_at=now,
        )
        try:
            await self._coll.insert_one(record.model_dump(mode="json"))
        except DuplicateKeyError:
            return None
        return record

    async def get(self, exception_id: str) -> Optional[IngestionRecord]:
        doc = await self._coll.find_one({"exception_id": exception_id}, projection={"_id": False})
        return IngestionRecord.model_validate(doc) if doc else None

    async def list(
        self,
        *,
        exception_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[IngestionRecord]:
        query: Dict[str, Any] = {}
        if exception_type:
            query["exception_type"] = exception_type
        if status:
            query["status"] = status

        cursor = (
            self._coll.find(query, projection={"_id": False})
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return [IngestionRecord.model_validate(d) async for d in cursor]

    async def list_by_status(
        self, status: IngestionStatus, *, limit: int = 200
    ) -> List[IngestionRecord]:
        cursor = (
            self._coll.find({"status": status.value}, projection={"_id": False})
            .sort("created_at", 1)
            .limit(limit)
        )
        return [IngestionRecord.model_validate(d) async for d in cursor]

    # --- lifecycle transitions (guarded: only fire from an expected current state) ---

    async def _transition(
        self,
        exception_id: str,
        status: IngestionStatus,
        *,
        expected: set[IngestionStatus],
        detail: Optional[str] = None,
        set_fields: Optional[Dict[str, Any]] = None,
    ) -> Optional[IngestionRecord]:
        """Advance the record only if its current status is in ``expected``.

        Returns the updated record, or ``None`` if the guard did not match (record
        missing or already past this transition) — making replays and illegal
        transitions safe no-ops.
        """
        now = _utcnow()
        change = StatusChange(status=status, at=now, detail=detail).model_dump(mode="json")
        updates: Dict[str, Any] = {"status": status.value, "updated_at": now.isoformat()}
        if set_fields:
            updates.update(set_fields)
        doc = await self._coll.find_one_and_update(
            {"exception_id": exception_id, "status": {"$in": [s.value for s in expected]}},
            {"$set": updates, "$push": {"status_history": change}},
            projection={"_id": False},
            return_document=ReturnDocument.AFTER,
        )
        return IngestionRecord.model_validate(doc) if doc else None

    async def mark_dispatched(
        self, exception_id: str, *, resolution: Dict[str, Any], detail: Optional[str] = None
    ) -> Optional[IngestionRecord]:
        return await self._transition(
            exception_id, IngestionStatus.DISPATCHED,
            expected={IngestionStatus.RECEIVED},
            detail=detail, set_fields={"resolution": resolution},
        )

    async def mark_no_process(
        self, exception_id: str, *, no_match: Dict[str, Any], detail: Optional[str] = None
    ) -> Optional[IngestionRecord]:
        return await self._transition(
            exception_id, IngestionStatus.NO_PROCESS,
            expected={IngestionStatus.RECEIVED},
            detail=detail, set_fields={"no_match": no_match},
        )

    async def mark_accepted(
        self, exception_id: str, *, process_instance_id: str, detail: Optional[str] = None
    ) -> Optional[IngestionRecord]:
        return await self._transition(
            exception_id, IngestionStatus.ACCEPTED,
            expected={IngestionStatus.DISPATCHED},
            detail=detail, set_fields={"process_instance_id": process_instance_id},
        )

    async def mark_rejected(
        self, exception_id: str, *, rejection: Dict[str, Any], detail: Optional[str] = None
    ) -> Optional[IngestionRecord]:
        return await self._transition(
            exception_id, IngestionStatus.REJECTED,
            expected={IngestionStatus.DISPATCHED},
            detail=detail, set_fields={"rejection": rejection},
        )
