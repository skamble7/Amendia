# app/dal/bpmn_repo.py
"""BPMN document store, keyed by (pack_key, version)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from motor.motor_asyncio import AsyncIOMotorCollection

from app.dal.base import utcnow_iso

_PROJECTION = {"_id": 0}


class BpmnRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def upsert(self, pack_key: str, version: str, *, xml: str, sha256: str,
                     content_type: str = "application/xml") -> None:
        await self._coll.replace_one(
            {"pack_key": pack_key, "version": version},
            {
                "pack_key": pack_key, "version": version,
                "xml": xml, "sha256": sha256, "content_type": content_type,
                "created_at": utcnow_iso(),
            },
            upsert=True,
        )

    async def get(self, pack_key: str, version: str) -> Optional[Dict[str, Any]]:
        return await self._coll.find_one({"pack_key": pack_key, "version": version}, projection=_PROJECTION)

    async def get_xml(self, pack_key: str, version: str) -> Optional[str]:
        doc = await self.get(pack_key, version)
        return doc.get("xml") if doc else None
