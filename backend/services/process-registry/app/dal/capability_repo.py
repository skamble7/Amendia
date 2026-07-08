# app/dal/capability_repo.py
"""Capability descriptor repository (registry is the write owner)."""
from __future__ import annotations

from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from amendia_contracts.capability import CapabilityDescriptor
from app.dal.base import DuplicateError, stamp_new, utcnow_iso

_PROJECTION = {"_id": 0}


class CapabilityRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def insert(self, cap: CapabilityDescriptor) -> CapabilityDescriptor:
        doc = stamp_new(cap.to_doc())
        try:
            await self._coll.insert_one(doc)
        except DuplicateKeyError:
            raise DuplicateError(f"capability {cap.capability_id}@{cap.version}")
        doc.pop("_id", None)
        return CapabilityDescriptor.model_validate(doc)

    async def get(self, capability_id: str, version: str) -> Optional[CapabilityDescriptor]:
        doc = await self._coll.find_one(
            {"capability_id": capability_id, "version": version}, projection=_PROJECTION
        )
        return CapabilityDescriptor.model_validate(doc) if doc else None

    async def list_by_id(self, capability_id: str) -> List[CapabilityDescriptor]:
        cursor = self._coll.find({"capability_id": capability_id}, projection=_PROJECTION)
        return [CapabilityDescriptor.model_validate(d) async for d in cursor]

    async def list(
        self, *, status: Optional[str] = None, kind: Optional[str] = None,
        limit: int = 50, offset: int = 0,
    ) -> List[CapabilityDescriptor]:
        query: dict = {}
        if status:
            query["status"] = status
        if kind:
            query["kind"] = kind
        cursor = (
            self._coll.find(query, projection=_PROJECTION)
            .sort("created_at", -1).skip(offset).limit(limit)
        )
        return [CapabilityDescriptor.model_validate(d) async for d in cursor]

    async def set_status(self, capability_id: str, version: str, status: str) -> Optional[CapabilityDescriptor]:
        doc = await self._coll.find_one_and_update(
            {"capability_id": capability_id, "version": version},
            {"$set": {"status": status, "updated_at": utcnow_iso()}},
            projection=_PROJECTION, return_document=ReturnDocument.AFTER,
        )
        return CapabilityDescriptor.model_validate(doc) if doc else None
