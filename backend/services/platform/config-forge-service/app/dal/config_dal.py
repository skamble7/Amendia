# app/dal/config_dal.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.models.config_entry import ConfigEntry, ConfigEntryCreate, ConfigEntryUpdate, build_ref

COL = "config_entries"

__all__ = [
    "create_entry",
    "get_entry_by_id",
    "get_entry_by_ref",
    "list_entries",
    "update_entry",
    "delete_entry",
]


async def create_entry(db: AsyncIOMotorDatabase, data: ConfigEntryCreate) -> ConfigEntry:
    now = datetime.now(timezone.utc)
    ref = build_ref(data.env, data.kind.value, data.provider, data.platform, data.name)

    doc = {
        "_id": str(uuid.uuid4()),
        "ref": ref,
        "env": data.env,
        "kind": data.kind.value,
        "provider": data.provider,
        "platform": data.platform,
        "name": data.name,
        "description": data.description,
        "data": data.data,
        "created_by": data.created_by,
        "created_at": now,
        "updated_at": now,
    }

    try:
        await db[COL].insert_one(doc)
    except DuplicateKeyError:
        raise ValueError(f"A config entry with ref '{ref}' already exists.")

    return _to_model(doc)


async def get_entry_by_id(db: AsyncIOMotorDatabase, entry_id: str) -> Optional[ConfigEntry]:
    doc = await db[COL].find_one({"_id": entry_id})
    return _to_model(doc) if doc else None


async def get_entry_by_ref(db: AsyncIOMotorDatabase, ref: str) -> Optional[ConfigEntry]:
    doc = await db[COL].find_one({"ref": ref})
    return _to_model(doc) if doc else None


async def list_entries(
    db: AsyncIOMotorDatabase,
    *,
    env: Optional[str] = None,
    kind: Optional[str] = None,
    provider: Optional[str] = None,
    platform: Optional[str] = None,
) -> List[ConfigEntry]:
    query: Dict[str, Any] = {}
    if env:
        query["env"] = env
    if kind:
        query["kind"] = kind
    if provider:
        query["provider"] = provider
    if platform:
        query["platform"] = platform
    cur = db[COL].find(query).sort("created_at", 1)
    return [_to_model(d) async for d in cur]


async def update_entry(
    db: AsyncIOMotorDatabase, entry_id: str, patch: ConfigEntryUpdate
) -> Optional[ConfigEntry]:
    upd: Dict[str, Any] = {k: v for k, v in patch.model_dump(exclude_unset=True).items()}
    if not upd:
        doc = await db[COL].find_one({"_id": entry_id})
        return _to_model(doc) if doc else None

    upd["updated_at"] = datetime.now(timezone.utc)
    res = await db[COL].find_one_and_update(
        {"_id": entry_id},
        {"$set": upd},
        return_document=ReturnDocument.AFTER,
    )
    return _to_model(res) if res else None


async def delete_entry(db: AsyncIOMotorDatabase, entry_id: str) -> bool:
    res = await db[COL].delete_one({"_id": entry_id})
    return res.deleted_count == 1


def _to_model(doc: Optional[Dict[str, Any]]) -> Optional[ConfigEntry]:
    if not doc:
        return None
    return ConfigEntry(
        _id=str(doc["_id"]),
        ref=doc["ref"],
        env=doc["env"],
        kind=doc["kind"],
        provider=doc.get("provider"),
        platform=doc.get("platform"),
        name=doc["name"],
        description=doc.get("description"),
        data=doc["data"],
        created_by=doc.get("created_by"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )
