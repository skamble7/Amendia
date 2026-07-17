# app/dal/message_repo.py
"""Message-subscription + pending-message repositories (ADR-031 Phase 2.4).

Mirrors the timer repo: idempotent register (upsert on the unique ``(instance, element)`` index),
a match lookup by ``message_name`` + business anchor, and a guarded ``pending → consumed`` flip.
The pending buffer holds an unmatched inbound message until its subscription registers.
"""
from __future__ import annotations

from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument

from app.models.common import utcnow
from app.models.message import (
    MessageSubscription,
    PendingMessage,
    SubscriptionStatus,
)

_PROJ = {"_id": 0}


def _iso() -> str:
    return utcnow().isoformat()


class MessageSubscriptionRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def register(self, sub: MessageSubscription) -> MessageSubscription:
        """Idempotent register: insert if absent; a crash-replay re-entry keeps the existing row."""
        key = {"process_instance_id": sub.process_instance_id, "element_id": sub.element_id}
        await self._coll.update_one(key, {"$setOnInsert": sub.to_doc()}, upsert=True)
        stored = await self._coll.find_one(key, projection=_PROJ)
        return MessageSubscription.model_validate(stored)

    async def find_match(self, message_name: str, *, exception_id: Optional[str] = None,
                         correlation_id: Optional[str] = None,
                         status: SubscriptionStatus = SubscriptionStatus.PENDING) -> Optional[MessageSubscription]:
        """A subscription in ``status`` for this message + anchor (correlation_id preferred, else
        exception_id). Defaults to pending (the delivery target); a consumed match lets the intake
        distinguish a duplicate (409) from an unknown message (404). Returns None when none match."""
        anchor: dict = {}
        if correlation_id is not None:
            anchor["correlation_id"] = correlation_id
        elif exception_id is not None:
            anchor["exception_id"] = exception_id
        else:
            return None
        doc = await self._coll.find_one(
            {"message_name": message_name, "status": status.value, **anchor}, projection=_PROJ)
        return MessageSubscription.model_validate(doc) if doc else None

    async def get(self, subscription_id: str) -> Optional[MessageSubscription]:
        doc = await self._coll.find_one({"subscription_id": subscription_id}, projection=_PROJ)
        return MessageSubscription.model_validate(doc) if doc else None

    async def mark(self, subscription_id: str, status: SubscriptionStatus) -> Optional[MessageSubscription]:
        """Guarded pending → status (consumed/cancelled). None if it was not pending — the once-only
        guard for delivery."""
        doc = await self._coll.find_one_and_update(
            {"subscription_id": subscription_id, "status": SubscriptionStatus.PENDING.value},
            {"$set": {"status": status.value, "updated_at": _iso()}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        doc.pop("_id", None)
        return MessageSubscription.model_validate(doc)

    async def cancel_others_for_instance(self, process_instance_id: str, *, keep_element_id: str) -> int:
        """Cancel all other pending subscriptions for this instance (event-gateway losers)."""
        res = await self._coll.update_many(
            {"process_instance_id": process_instance_id, "status": SubscriptionStatus.PENDING.value,
             "element_id": {"$ne": keep_element_id}},
            {"$set": {"status": SubscriptionStatus.CANCELLED.value, "updated_at": _iso()}},
        )
        return res.modified_count

    async def cancel_for_instance(self, process_instance_id: str) -> int:
        res = await self._coll.update_many(
            {"process_instance_id": process_instance_id, "status": SubscriptionStatus.PENDING.value},
            {"$set": {"status": SubscriptionStatus.CANCELLED.value, "updated_at": _iso()}},
        )
        return res.modified_count

    async def list_for_instance(self, process_instance_id: str) -> List[MessageSubscription]:
        cursor = self._coll.find({"process_instance_id": process_instance_id}, projection=_PROJ)
        return [MessageSubscription.model_validate(d) async for d in cursor]


class PendingMessageRepository:
    """The ordering buffer: an inbound message that arrived before its subscription registered."""

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def buffer(self, msg: PendingMessage) -> None:
        await self._coll.insert_one(msg.to_doc())

    async def pop_match(self, message_name: str, *, exception_id: Optional[str] = None,
                        correlation_id: Optional[str] = None) -> Optional[PendingMessage]:
        """Atomically take one buffered message matching this subscription's message + anchor."""
        clauses = []
        if correlation_id is not None:
            clauses.append({"correlation_id": correlation_id})
        if exception_id is not None:
            clauses.append({"exception_id": exception_id})
        if not clauses:
            return None
        doc = await self._coll.find_one_and_delete(
            {"message_name": message_name, "$or": clauses}
        )
        if doc is None:
            return None
        doc.pop("_id", None)
        return PendingMessage.model_validate(doc)
