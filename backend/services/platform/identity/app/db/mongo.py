# app/db/mongo.py
"""Mongo client lifecycle + index creation for the identity aggregates.

``users`` — the durable Amendia user + its linked IdP identities. ``role_assignments``
— (user, role) grants. ``pending_role_assignments`` — role grants keyed by email,
seeded before anyone logs in and materialised onto the user at JIT-provision time.
"""
from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING

logger = logging.getLogger(__name__)

USERS = "users"
ROLE_ASSIGNMENTS = "role_assignments"
PENDING_ROLE_ASSIGNMENTS = "pending_role_assignments"


async def create_indexes(db: AsyncIOMotorDatabase) -> None:
    await db[USERS].create_index("amendia_user_id", unique=True)
    # Multikey unique across the identities array: one (iss, sub) maps to one user.
    await db[USERS].create_index(
        [("identities.iss", ASCENDING), ("identities.sub", ASCENDING)], unique=True
    )
    await db[USERS].create_index("email")
    await db[USERS].create_index("status")

    await db[ROLE_ASSIGNMENTS].create_index(
        [("amendia_user_id", ASCENDING), ("role", ASCENDING)], unique=True
    )
    await db[ROLE_ASSIGNMENTS].create_index("role")

    await db[PENDING_ROLE_ASSIGNMENTS].create_index(
        [("email", ASCENDING), ("role", ASCENDING)], unique=True
    )


class MongoClient:
    def __init__(self, uri: str, db_name: str) -> None:
        self._uri = uri
        self._db_name = db_name
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None

    async def connect(self) -> None:
        self._client = AsyncIOMotorClient(self._uri)
        self._db = self._client[self._db_name]
        await create_indexes(self._db)
        logger.info("Connected to MongoDB db=%s", self._db_name)

    async def ping(self) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:  # pragma: no cover - defensive
            return False

    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise RuntimeError("MongoClient not connected")
        return self._db

    def collection(self, name: str) -> AsyncIOMotorCollection:
        return self.db[name]

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("Closed MongoDB connection")
