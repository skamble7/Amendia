# app/dal/capability_repo.py
"""Capability descriptor repository."""
from __future__ import annotations

from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from app.dal.base import DuplicateError, latest_active, sort_by_semver_desc, stamp_new
from app.models.capability import CapabilityDescriptor

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

    async def get_raw(self, capability_id: str, version: str) -> Optional[dict]:
        return await self._coll.find_one(
            {"capability_id": capability_id, "version": version}, projection=_PROJECTION
        )

    async def list_versions(self, capability_id: str) -> List[CapabilityDescriptor]:
        cursor = self._coll.find({"capability_id": capability_id}, projection=_PROJECTION)
        items = [CapabilityDescriptor.model_validate(d) async for d in cursor]
        return sort_by_semver_desc(items)

    async def get_latest_active(self, capability_id: str) -> Optional[CapabilityDescriptor]:
        return latest_active(await self.list_versions(capability_id))

    async def list(
        self,
        *,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CapabilityDescriptor]:
        query: dict = {}
        if status:
            query["status"] = status
        if kind:
            query["kind"] = kind
        cursor = (
            self._coll.find(query, projection=_PROJECTION)
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return [CapabilityDescriptor.model_validate(d) async for d in cursor]
