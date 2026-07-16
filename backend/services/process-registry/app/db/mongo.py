# app/db/mongo.py
"""Mongo client lifecycle + index creation.

The registry is the WRITE owner of the three catalog collections (also read by the
agent-runtime) plus its own ``bpmn_documents`` store.
"""
from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

logger = logging.getLogger(__name__)

CAPABILITIES = "capabilities"
ARTIFACT_SCHEMAS = "artifact_schemas"
PROCESS_PACKS = "process_packs"
BPMN_DOCUMENTS = "bpmn_documents"
# Registry-only sidecar collections (kept OFF the shared process_packs doc so its
# shape stays a pure manifest that the agent-runtime can also read).
VALIDATION_REPORTS = "validation_reports"
PACK_RESOLUTIONS = "pack_resolutions"
# Authoring scratch space for the form-driven onboarding wizard. NOT a contract
# document — nothing here is written to the shared catalog collections until commit.
ONBOARDING_SESSIONS = "onboarding_sessions"


async def create_indexes(db: AsyncIOMotorDatabase) -> None:
    await db[CAPABILITIES].create_index(
        [("capability_id", ASCENDING), ("version", ASCENDING)], unique=True
    )
    await db[CAPABILITIES].create_index("status")
    await db[CAPABILITIES].create_index("kind")

    await db[ARTIFACT_SCHEMAS].create_index(
        [("artifact_key", ASCENDING), ("version", ASCENDING)], unique=True
    )
    await db[ARTIFACT_SCHEMAS].create_index("status")

    await db[PROCESS_PACKS].create_index(
        [("pack_key", ASCENDING), ("version", ASCENDING)], unique=True
    )
    await db[PROCESS_PACKS].create_index("status")

    for coll in (BPMN_DOCUMENTS, VALIDATION_REPORTS, PACK_RESOLUTIONS):
        await db[coll].create_index(
            [("pack_key", ASCENDING), ("version", ASCENDING)], unique=True
        )

    await db[ONBOARDING_SESSIONS].create_index("session_id", unique=True)
    await db[ONBOARDING_SESSIONS].create_index([("created_by", ASCENDING), ("updated_at", DESCENDING)])

    for coll in (CAPABILITIES, ARTIFACT_SCHEMAS, PROCESS_PACKS):
        await db[coll].create_index([("created_at", DESCENDING)])


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
