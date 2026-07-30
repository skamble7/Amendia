# app/dal/tickets_repo.py
"""Data-access layer for stored dine-in tickets — CRUD over Mongo, no business logic (mirrors exceptions_repo)."""
from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from app.models.ticket import StoredTicket


class DuplicateTicketError(Exception):
    """Raised when a ticket_id already exists (mapped to HTTP 409)."""

    def __init__(self, ticket_id: str) -> None:
        self.ticket_id = ticket_id
        super().__init__(f"ticket_id '{ticket_id}' already exists")


class TicketRepository:
    """Async repository over the tickets collection."""

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def insert(self, stored: StoredTicket) -> StoredTicket:
        try:
            await self._coll.insert_one(stored.model_dump(mode="json"))
        except DuplicateKeyError as exc:
            raise DuplicateTicketError(stored.ticket_id) from exc
        return stored

    async def get(self, ticket_id: str) -> Optional[StoredTicket]:
        doc = await self._coll.find_one({"ticket_id": ticket_id}, projection={"_id": False})
        return StoredTicket.model_validate(doc) if doc else None
