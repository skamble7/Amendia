# app/dal/capability_repo.py
"""Capability descriptor repository (registry is the write owner).

ADR-060: every row is OWNED by exactly one pack version. Reads/writes are scoped by
``(pack_key, pack_version)`` — there is no global-by-id lookup. The same ``capability_id`` may exist under
different packs as independent, owned copies. ``insert`` takes the owner from the descriptor (which now
carries ``pack_key``/``pack_version``); all other methods take the pack coordinates explicitly.
"""
from __future__ import annotations

import re
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
            raise DuplicateError(
                f"capability {cap.capability_id}@{cap.version} for pack {cap.pack_key}@{cap.pack_version}"
            )
        doc.pop("_id", None)
        return CapabilityDescriptor.model_validate(doc)

    async def get(
        self, pack_key: str, pack_version: str, capability_id: str, version: str
    ) -> Optional[CapabilityDescriptor]:
        doc = await self._coll.find_one(
            {"pack_key": pack_key, "pack_version": pack_version,
             "capability_id": capability_id, "version": version},
            projection=_PROJECTION,
        )
        return CapabilityDescriptor.model_validate(doc) if doc else None

    async def list_by_id(
        self, pack_key: str, pack_version: str, capability_id: str
    ) -> List[CapabilityDescriptor]:
        cursor = self._coll.find(
            {"pack_key": pack_key, "pack_version": pack_version, "capability_id": capability_id},
            projection=_PROJECTION,
        )
        return [CapabilityDescriptor.model_validate(d) async for d in cursor]

    async def list_owned(self, pack_key: str, pack_version: str) -> List[CapabilityDescriptor]:
        """Every capability the given pack version owns (the ADR-060 ownership query)."""
        cursor = self._coll.find(
            {"pack_key": pack_key, "pack_version": pack_version}, projection=_PROJECTION
        )
        return [CapabilityDescriptor.model_validate(d) async for d in cursor]

    async def delete_owned(self, pack_key: str, pack_version: str) -> int:
        """ADR-061: physically remove every capability owned by ``(pack_key, pack_version)`` — a pure cascade
        (ADR-060 ownership; nothing is shared, so no reference-counting). Idempotent."""
        return (await self._coll.delete_many(
            {"pack_key": pack_key, "pack_version": pack_version})).deleted_count

    async def list(
        self, *, pack_key: Optional[str] = None, pack_version: Optional[str] = None,
        status: Optional[str] = None, kind: Optional[str] = None,
        q: Optional[str] = None, limit: int = 50, offset: int = 0,
    ) -> List[CapabilityDescriptor]:
        """Browse owned rows. ADR-060: with a pack given, scoped to that pack; otherwise all owned rows."""
        query: dict = {}
        if pack_key:
            query["pack_key"] = pack_key
        if pack_version:
            query["pack_version"] = pack_version
        if status:
            query["status"] = status
        if kind:
            query["kind"] = kind
        # Free-text: case-insensitive substring over capability_id + title (the on-demand reuse search).
        if q:
            rx = {"$regex": re.escape(q), "$options": "i"}
            query["$or"] = [{"capability_id": rx}, {"title": rx}]
        cursor = (
            self._coll.find(query, projection=_PROJECTION)
            .sort("created_at", -1).skip(offset).limit(limit)
        )
        return [CapabilityDescriptor.model_validate(d) async for d in cursor]

    async def set_status(
        self, pack_key: str, pack_version: str, capability_id: str, version: str, status: str
    ) -> Optional[CapabilityDescriptor]:
        doc = await self._coll.find_one_and_update(
            {"pack_key": pack_key, "pack_version": pack_version,
             "capability_id": capability_id, "version": version},
            {"$set": {"status": status, "updated_at": utcnow_iso()}},
            projection=_PROJECTION, return_document=ReturnDocument.AFTER,
        )
        return CapabilityDescriptor.model_validate(doc) if doc else None
