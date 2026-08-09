# app/dal/cohort_def_repo.py
"""ADR-063 Phase 2 — cohort-definition repository (registry-owned)."""
from __future__ import annotations

from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from amendia_contracts.common import utcnow

from app.dal.base import DuplicateError
from app.models.cohort import CohortDefinition, CohortDefinitionUpdate

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

    async def update(self, cohort_def_id: str, patch: CohortDefinitionUpdate) -> Optional[CohortDefinition]:
        """Update the MUTABLE fields of an existing definition. Preserves ``created_at`` (untouched), bumps
        ``updated_at``, and never changes ``cohort_def_id`` (not in the patch). Returns None if absent."""
        updates = patch.model_dump(mode="json")
        updates["updated_at"] = utcnow().isoformat()
        doc = await self._coll.find_one_and_update(
            {"cohort_def_id": cohort_def_id}, {"$set": updates},
            projection=_PROJECTION, return_document=ReturnDocument.AFTER,
        )
        return CohortDefinition.model_validate(doc) if doc else None

    async def delete(self, cohort_def_id: str) -> int:
        return (await self._coll.delete_many({"cohort_def_id": cohort_def_id})).deleted_count
