# app/dal/onboarding_repo.py
"""OnboardingSession repository (registry-owned authoring scratch space).

Unlike the catalog repos, the whole aggregate is rewritten on each transition — the
state machine reads-modifies-writes the full session. Keyed by ``session_id``."""
from __future__ import annotations

from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument

from amendia_contracts.common import utcnow

from app.models.onboarding import OnboardingSession

_PROJECTION = {"_id": 0}


class OnboardingRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def insert(self, session: OnboardingSession) -> OnboardingSession:
        await self._coll.insert_one(session.to_doc())
        return session

    async def get(self, session_id: str) -> Optional[OnboardingSession]:
        doc = await self._coll.find_one({"session_id": session_id}, projection=_PROJECTION)
        return OnboardingSession.model_validate(doc) if doc else None

    async def save(self, session: OnboardingSession) -> OnboardingSession:
        session.updated_at = utcnow()
        await self._coll.find_one_and_update(
            {"session_id": session.session_id},
            {"$set": session.to_doc()},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return session

    async def list_for(self, created_by: str, *, limit: int = 50) -> List[OnboardingSession]:
        cursor = (
            self._coll.find({"created_by": created_by}, projection=_PROJECTION)
            .sort("updated_at", -1).limit(limit)
        )
        return [OnboardingSession.model_validate(d) async for d in cursor]

    async def delete(self, session_id: str) -> bool:
        res = await self._coll.delete_one({"session_id": session_id})
        return res.deleted_count > 0
