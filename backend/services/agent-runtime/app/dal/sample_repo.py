# app/dal/sample_repo.py
"""Sample-exception repository — seed-only storage of the reference envelope.

Stored as-is (no contract model in agent-runtime scope validates the wire envelope);
kept so the execution slice has a fetch-back fixture available.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from motor.motor_asyncio import AsyncIOMotorCollection


class SampleExceptionRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def upsert(self, sample: Dict[str, Any]) -> None:
        exception_id = sample["exception_id"]
        await self._coll.replace_one({"exception_id": exception_id}, sample, upsert=True)

    async def get(self, exception_id: str) -> Optional[Dict[str, Any]]:
        return await self._coll.find_one({"exception_id": exception_id}, projection={"_id": 0})
