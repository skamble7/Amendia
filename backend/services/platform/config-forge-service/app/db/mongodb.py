# app/db/mongodb.py
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def get_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        _client = AsyncIOMotorClient(settings.MONGO_URI)
        _db = _client[settings.MONGO_DB]
        await _ensure_indexes(_db)
    return _db


async def _ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await db["config_entries"].create_index("ref", unique=True)
    await db["config_entries"].create_index([("kind", 1), ("env", 1)])


async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None
