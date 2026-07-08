# app/dal/artifact_schema_repo.py
"""Artifact schema registration repository (registry is the write owner)."""
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
            raise DuplicateError(f"artifact schema {reg.artifact_key}@{reg.version}")
        doc.pop("_id", None)
        return ArtifactSchemaRegistration.model_validate(doc)

    async def get(self, artifact_key: str, version: str) -> Optional[ArtifactSchemaRegistration]:
        doc = await self._coll.find_one(
            {"artifact_key": artifact_key, "version": version}, projection=_PROJECTION
        )
        return ArtifactSchemaRegistration.model_validate(doc) if doc else None

    async def list_by_key(self, artifact_key: str) -> List[ArtifactSchemaRegistration]:
        cursor = self._coll.find({"artifact_key": artifact_key}, projection=_PROJECTION)
        return [ArtifactSchemaRegistration.model_validate(d) async for d in cursor]

    async def previous_version(
        self, artifact_key: str, version: str
    ) -> Optional[ArtifactSchemaRegistration]:
        """The highest registered version strictly lower than ``version`` (for compat diff)."""
        target = Version(version)
        best: Optional[ArtifactSchemaRegistration] = None
        best_v: Optional[Version] = None
        for reg in await self.list_by_key(artifact_key):
            v = Version(reg.version)
            if v < target and (best_v is None or v > best_v):
                best, best_v = reg, v
        return best

    async def list(
        self, *, status: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> List[ArtifactSchemaRegistration]:
        query: dict = {}
        if status:
            query["status"] = status
        cursor = (
            self._coll.find(query, projection=_PROJECTION)
            .sort("created_at", -1).skip(offset).limit(limit)
        )
        return [ArtifactSchemaRegistration.model_validate(d) async for d in cursor]

    async def set_status(
        self, artifact_key: str, version: str, status: str
    ) -> Optional[ArtifactSchemaRegistration]:
        doc = await self._coll.find_one_and_update(
            {"artifact_key": artifact_key, "version": version},
            {"$set": {"status": status, "updated_at": utcnow_iso()}},
            projection=_PROJECTION, return_document=ReturnDocument.AFTER,
        )
        return ArtifactSchemaRegistration.model_validate(doc) if doc else None
