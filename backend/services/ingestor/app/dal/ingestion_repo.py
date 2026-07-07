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
        tenant: str,
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
            tenant=tenant,
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
        tenant: Optional[str] = None,
        exception_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[IngestionRecord]:
        query: Dict[str, Any] = {}
        if tenant:
            query["tenant"] = tenant
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

    # --- lifecycle transitions (future: agent-runtime dispatch; not triggered yet) ---

    async def _transition(
        self, exception_id: str, status: IngestionStatus, detail: Optional[str]
    ) -> Optional[IngestionRecord]:
        now = _utcnow()
        change = StatusChange(status=status, at=now, detail=detail).model_dump(mode="json")
        doc = await self._coll.find_one_and_update(
            {"exception_id": exception_id},
            {
                "$set": {"status": status.value, "updated_at": now.isoformat()},
                "$push": {"status_history": change},
            },
            projection={"_id": False},
            return_document=ReturnDocument.AFTER,
        )
        return IngestionRecord.model_validate(doc) if doc else None

    async def mark_dispatched(
        self, exception_id: str, detail: Optional[str] = None
    ) -> Optional[IngestionRecord]:
        return await self._transition(exception_id, IngestionStatus.DISPATCHED, detail)

    async def mark_accepted(
        self, exception_id: str, detail: Optional[str] = None
    ) -> Optional[IngestionRecord]:
        return await self._transition(exception_id, IngestionStatus.ACCEPTED, detail)

    async def mark_rejected(
        self, exception_id: str, detail: Optional[str] = None
    ) -> Optional[IngestionRecord]:
        return await self._transition(exception_id, IngestionStatus.REJECTED, detail)
