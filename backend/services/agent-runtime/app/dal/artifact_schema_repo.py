# app/dal/artifact_schema_repo.py
"""Artifact schema registration repository."""
from __future__ import annotations

from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from app.dal.base import DuplicateError, latest_active, sort_by_semver_desc, stamp_new
from app.models.artifact_schema import ArtifactSchemaRegistration

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

    async def get_raw(self, artifact_key: str, version: str) -> Optional[dict]:
        return await self._coll.find_one(
            {"artifact_key": artifact_key, "version": version}, projection=_PROJECTION
        )

    async def list_versions(self, artifact_key: str) -> List[ArtifactSchemaRegistration]:
        cursor = self._coll.find({"artifact_key": artifact_key}, projection=_PROJECTION)
        items = [ArtifactSchemaRegistration.model_validate(d) async for d in cursor]
        return sort_by_semver_desc(items)

    async def get_latest_active(self, artifact_key: str) -> Optional[ArtifactSchemaRegistration]:
        return latest_active(await self.list_versions(artifact_key))

    async def list(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ArtifactSchemaRegistration]:
        query: dict = {}
        if status:
            query["status"] = status
        cursor = (
            self._coll.find(query, projection=_PROJECTION)
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return [ArtifactSchemaRegistration.model_validate(d) async for d in cursor]
