# app/dal/exceptions_repo.py
"""Data-access layer for stored exceptions — CRUD over Mongo, no business logic."""
from __future__ import annotations

from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from app.models.envelope import StoredException


class DuplicateExceptionError(Exception):
    """Raised when an exception_id already exists (mapped to HTTP 409)."""

    def __init__(self, exception_id: str) -> None:
        self.exception_id = exception_id
        super().__init__(f"exception_id '{exception_id}' already exists")


class ExceptionRepository:
    """Async repository over the exceptions collection."""

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def insert(self, stored: StoredException) -> StoredException:
        doc = stored.model_dump(mode="json")
        try:
            await self._coll.insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateExceptionError(stored.exception_id) from exc
        return stored

    async def get(self, exception_id: str) -> Optional[StoredException]:
        doc = await self._coll.find_one({"exception_id": exception_id}, projection={"_id": False})
        return StoredException.model_validate(doc) if doc else None

    async def list(
        self,
        *,
        tenant: Optional[str] = None,
        exception_type: Optional[str] = None,
        status: Optional[str] = None,
        reason_code: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[StoredException]:
        query: dict = {}
        if tenant:
            query["tenant"] = tenant
        if exception_type:
            query["exception_type"] = exception_type
        if status:
            query["status"] = status
        if reason_code:
            query["reason_codes"] = reason_code

        cursor = (
            self._coll.find(query, projection={"_id": False})
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return [StoredException.model_validate(d) async for d in cursor]
