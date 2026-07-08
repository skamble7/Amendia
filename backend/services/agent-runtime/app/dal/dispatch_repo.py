# app/dal/dispatch_repo.py
"""Dispatch-log repository (records inbound dispatch events; used by the execution
slice later). Included now so the collection + 409 semantics exist."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from app.dal.base import DuplicateError, stamp_new
from app.models.dispatch import ExceptionDispatchedEvent

_PROJECTION = {"_id": 0}


class DispatchLogRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def insert(self, event: ExceptionDispatchedEvent) -> Dict[str, Any]:
        doc = stamp_new(event.to_doc())
        try:
            await self._coll.insert_one(doc)
        except DuplicateKeyError:
            raise DuplicateError(f"dispatch event {event.event_id}")
        doc.pop("_id", None)
        return doc

    async def get(self, event_id: str) -> Optional[Dict[str, Any]]:
        return await self._coll.find_one({"event_id": event_id}, projection=_PROJECTION)

    async def list(
        self,
        *,
        tenant: Optional[str] = None,
        exception_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query: dict = {}
        if tenant:
            query["tenant"] = tenant
        if exception_id:
            query["exception_id"] = exception_id
        cursor = (
            self._coll.find(query, projection=_PROJECTION)
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return [d async for d in cursor]
