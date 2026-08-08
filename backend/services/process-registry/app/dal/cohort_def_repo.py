# app/dal/cohort_def_repo.py
"""ADR-063 Phase 2 — cohort-definition repository (registry-owned)."""
from __future__ import annotations

from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from app.dal.base import DuplicateError
from app.models.cohort import CohortDefinition

_PROJECTION = {"_id": 0}


class CohortDefinitionRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def insert(self, definition: CohortDefinition) -> CohortDefinition:
        try:
            await self._coll.insert_one(definition.to_doc())
        except DuplicateKeyError:
            raise DuplicateError(f"cohort definition {definition.cohort_def_id}")
        return definition

    async def get(self, cohort_def_id: str) -> Optional[CohortDefinition]:
        doc = await self._coll.find_one({"cohort_def_id": cohort_def_id}, projection=_PROJECTION)
        return CohortDefinition.model_validate(doc) if doc else None

    async def list(self) -> List[CohortDefinition]:
        cursor = self._coll.find({}, projection=_PROJECTION).sort("cohort_def_id", 1)
        return [CohortDefinition.model_validate(d) async for d in cursor]

    async def delete(self, cohort_def_id: str) -> int:
        return (await self._coll.delete_many({"cohort_def_id": cohort_def_id})).deleted_count
