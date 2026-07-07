# app/db/mongo.py
"""Mongo client lifecycle: connect/close via the app lifespan, index creation."""
from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


class MongoClient:
    """Thin wrapper owning the motor client + the exceptions collection."""

    def __init__(self, uri: str, db_name: str, collection: str) -> None:
        self._uri = uri
        self._db_name = db_name
        self._collection = collection
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None

    async def connect(self) -> None:
        self._client = AsyncIOMotorClient(self._uri)
        self._db = self._client[self._db_name]
        await self.ensure_indexes()
        logger.info("Connected to MongoDB db=%s collection=%s", self._db_name, self._collection)

    async def ensure_indexes(self) -> None:
        coll = self.collection
        # Unique on exception_id → duplicate insert surfaces as HTTP 409 (idempotency).
        await coll.create_index("exception_id", unique=True)
        # Listing is sorted by created_at desc.
        await coll.create_index([("created_at", -1)])

    async def ping(self) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:  # pragma: no cover - defensive
            return False

    @property
    def collection(self) -> AsyncIOMotorCollection:
        if self._db is None:
            raise RuntimeError("MongoClient not connected")
        return self._db[self._collection]

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("Closed MongoDB connection")
