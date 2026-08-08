# app/dal/artifact_schema_repo.py
"""Artifact schema registration repository (registry is the write owner).

ADR-060: every row is OWNED by exactly one pack version. Reads/writes are scoped by
``(pack_key, pack_version)`` — no global-by-key lookup. ``insert`` takes the owner from the registration
(which now carries ``pack_key``/``pack_version``); all other methods take the pack coordinates explicitly.
"""
from __future__ import annotations

from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from packaging.version import Version
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from app.dal.base import DuplicateError, stamp_new, utcnow_iso

_PROJECTION = {"_id": 0}


class ArtifactSchemaRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def insert(self, reg: ArtifactSchemaRegistration) -> ArtifactSchemaRegistration:
        doc = stamp_new(reg.to_doc())
        try:
            await self._coll.insert_one(doc)
        except DuplicateKeyError:
            raise DuplicateError(
                f"artifact schema {reg.artifact_key}@{reg.version} for pack {reg.pack_key}@{reg.pack_version}"
            )
        doc.pop("_id", None)
        return ArtifactSchemaRegistration.model_validate(doc)

    async def get(
        self, pack_key: str, pack_version: str, artifact_key: str, version: str
    ) -> Optional[ArtifactSchemaRegistration]:
        doc = await self._coll.find_one(
            {"pack_key": pack_key, "pack_version": pack_version,
             "artifact_key": artifact_key, "version": version},
            projection=_PROJECTION,
        )
        return ArtifactSchemaRegistration.model_validate(doc) if doc else None

    async def list_by_key(
        self, pack_key: str, pack_version: str, artifact_key: str
    ) -> List[ArtifactSchemaRegistration]:
        cursor = self._coll.find(
            {"pack_key": pack_key, "pack_version": pack_version, "artifact_key": artifact_key},
            projection=_PROJECTION,
        )
        return [ArtifactSchemaRegistration.model_validate(d) async for d in cursor]

    async def list_owned(self, pack_key: str, pack_version: str) -> List[ArtifactSchemaRegistration]:
        """Every schema the given pack version owns (the ADR-060 ownership query)."""
        cursor = self._coll.find(
            {"pack_key": pack_key, "pack_version": pack_version}, projection=_PROJECTION
        )
        return [ArtifactSchemaRegistration.model_validate(d) async for d in cursor]

    async def delete_owned(self, pack_key: str, pack_version: str) -> int:
        """ADR-061: physically remove every artifact schema owned by ``(pack_key, pack_version)`` — a pure
        cascade (ADR-060 ownership; nothing is shared). Idempotent."""
        return (await self._coll.delete_many(
            {"pack_key": pack_key, "pack_version": pack_version})).deleted_count

    async def previous_version(
        self, pack_key: str, pack_version: str, artifact_key: str, version: str
    ) -> Optional[ArtifactSchemaRegistration]:
        """The highest version of ``artifact_key`` (within the same pack) strictly lower than ``version``."""
        target = Version(version)
        best: Optional[ArtifactSchemaRegistration] = None
        best_v: Optional[Version] = None
        for reg in await self.list_by_key(pack_key, pack_version, artifact_key):
            v = Version(reg.version)
            if v < target and (best_v is None or v > best_v):
                best, best_v = reg, v
        return best

    async def list(
        self, *, pack_key: Optional[str] = None, pack_version: Optional[str] = None,
        status: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> List[ArtifactSchemaRegistration]:
        """Browse owned rows. ADR-060: with a pack given, scoped to that pack; otherwise all owned rows."""
        query: dict = {}
        if pack_key:
            query["pack_key"] = pack_key
        if pack_version:
            query["pack_version"] = pack_version
        if status:
            query["status"] = status
        cursor = (
            self._coll.find(query, projection=_PROJECTION)
            .sort("created_at", -1).skip(offset).limit(limit)
        )
        return [ArtifactSchemaRegistration.model_validate(d) async for d in cursor]

    async def set_status(
        self, pack_key: str, pack_version: str, artifact_key: str, version: str, status: str
    ) -> Optional[ArtifactSchemaRegistration]:
        doc = await self._coll.find_one_and_update(
            {"pack_key": pack_key, "pack_version": pack_version,
             "artifact_key": artifact_key, "version": version},
            {"$set": {"status": status, "updated_at": utcnow_iso()}},
            projection=_PROJECTION, return_document=ReturnDocument.AFTER,
        )
        return ArtifactSchemaRegistration.model_validate(doc) if doc else None
