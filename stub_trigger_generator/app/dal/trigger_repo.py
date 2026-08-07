# app/dal/trigger_repo.py
"""Data-access layer for the single trigger-message store (ADR-059 D2) — CRUD over one ``trigger_messages``
collection, no business logic. Replaces the per-domain exceptions_repo / tickets_repo."""
from __future__ import annotations

from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from app.models.trigger import StoredTrigger


class DuplicateTriggerError(Exception):
    """Raised when a trigger_id already exists (mapped to HTTP 409 — preserves idempotency)."""

    def __init__(self, trigger_id: str) -> None:
        self.trigger_id = trigger_id
        super().__init__(f"trigger_id '{trigger_id}' already exists")


class TriggerRepository:
    """Async repository over the ``trigger_messages`` collection. Domain-blind."""

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def insert(self, stored: StoredTrigger) -> StoredTrigger:
        try:
            await self._coll.insert_one(stored.model_dump(mode="json"))
        except DuplicateKeyError as exc:
            raise DuplicateTriggerError(stored.trigger_id) from exc
        return stored

    async def get(self, trigger_id: str) -> Optional[StoredTrigger]:
        doc = await self._coll.find_one({"trigger_id": trigger_id}, projection={"_id": False})
        return StoredTrigger.model_validate(doc) if doc else None

    async def list(
        self,
        *,
        trigger_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[StoredTrigger]:
        query: dict = {}
        if trigger_type:
            query["trigger_type"] = trigger_type
        # ``status`` is a domain field — the store filters it via a payload dotpath without modelling it,
        # keeping the store domain-blind while still supporting the dev listing filter.
        if status:
            query["payload.status"] = status
        cursor = (
            self._coll.find(query, projection={"_id": False})
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return [StoredTrigger.model_validate(d) async for d in cursor]
