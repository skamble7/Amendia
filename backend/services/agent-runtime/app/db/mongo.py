# app/db/mongo.py
"""Mongo client lifecycle + index creation for every aggregate collection."""
from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

logger = logging.getLogger(__name__)


async def create_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create every aggregate's indexes (module-level so tests can reuse it)."""
    await db[PROCESS_PACKS].create_index(
        [("pack_key", ASCENDING), ("version", ASCENDING)], unique=True
    )
    await db[PROCESS_PACKS].create_index("status")

    await db[CAPABILITIES].create_index(
        [("capability_id", ASCENDING), ("version", ASCENDING)], unique=True
    )
    await db[CAPABILITIES].create_index("status")
    await db[CAPABILITIES].create_index("kind")

    await db[ARTIFACT_SCHEMAS].create_index(
        [("artifact_key", ASCENDING), ("version", ASCENDING)], unique=True
    )
    await db[ARTIFACT_SCHEMAS].create_index("status")

    await db[PROCESS_INSTANCES].create_index("process_instance_id", unique=True)
    await db[PROCESS_INSTANCES].create_index("idempotency_key", unique=True)
    await db[PROCESS_INSTANCES].create_index("exception_id")

    await db[HITL_TASKS].create_index("task_id", unique=True)
    await db[HITL_TASKS].create_index([("status", ASCENDING), ("role", ASCENDING)])
    await db[HITL_TASKS].create_index("process_instance_id")

    await db[DISPATCH_LOG].create_index("event_id", unique=True)
    await db[DISPATCH_LOG].create_index("exception_id")

    await db[SAMPLE_EXCEPTIONS].create_index("exception_id", unique=True)

    # ADR-027 Phase 2.2 timer substrate. Idempotent re-register: unique on (instance, element, kind)
    # so re-entering a node (crash replay) upserts rather than duplicating. The poller scans by
    # (status, fire_at) for due pending timers.
    await db[TIMERS].create_index(
        [("process_instance_id", ASCENDING), ("element_id", ASCENDING), ("kind", ASCENDING)],
        unique=True,
    )
    await db[TIMERS].create_index([("status", ASCENDING), ("fire_at", ASCENDING)])

    # ADR-031 Phase 2.4 message substrate. Idempotent re-register unique on (instance, element); fast
    # delivery lookup by (message_name, anchor). Pending buffer holds unmatched inbound messages (TTL).
    await db[MESSAGE_SUBSCRIPTIONS].create_index(
        [("process_instance_id", ASCENDING), ("element_id", ASCENDING)], unique=True)
    await db[MESSAGE_SUBSCRIPTIONS].create_index([("message_name", ASCENDING), ("exception_id", ASCENDING)])
    await db[MESSAGE_SUBSCRIPTIONS].create_index([("message_name", ASCENDING), ("correlation_id", ASCENDING)])
    await db[PENDING_MESSAGES].create_index([("message_name", ASCENDING), ("correlation_id", ASCENDING)])
    await db[PENDING_MESSAGES].create_index("created_at", expireAfterSeconds=3600)  # TTL buffer

    for coll in (PROCESS_PACKS, CAPABILITIES, ARTIFACT_SCHEMAS, PROCESS_INSTANCES, HITL_TASKS, DISPATCH_LOG):
        await db[coll].create_index([("created_at", DESCENDING)])

# Collection names.
PROCESS_PACKS = "process_packs"
CAPABILITIES = "capabilities"
ARTIFACT_SCHEMAS = "artifact_schemas"
PROCESS_INSTANCES = "process_instances"
HITL_TASKS = "hitl_tasks"
DISPATCH_LOG = "dispatch_log"
TIMERS = "timers"                        # ADR-027 Phase 2.2 durable timer substrate
MESSAGE_SUBSCRIPTIONS = "message_subscriptions"  # ADR-031 Phase 2.4 message substrate
PENDING_MESSAGES = "pending_messages"    # ADR-031 Phase 2.4 ordering buffer (TTL'd)
SAMPLE_EXCEPTIONS = "sample_exceptions"  # seed-only helper collection


class MongoClient:
    """Owns the motor client + database and creates indexes on startup."""

    def __init__(self, uri: str, db_name: str) -> None:
        self._uri = uri
        self._db_name = db_name
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None

    async def connect(self) -> None:
        self._client = AsyncIOMotorClient(self._uri)
        self._db = self._client[self._db_name]
        await self.ensure_indexes()
        logger.info("Connected to MongoDB db=%s", self._db_name)

    async def ensure_indexes(self) -> None:
        await create_indexes(self.db)

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
