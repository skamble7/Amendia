# app/dal/pack_repo.py
"""ProcessPack repository.

The stored document is the manifest payload + store timestamps + the raw BPMN XML
(kept in the same doc under ``bpmn_xml``, served separately by the API). No business
logic here — validation of bindings/capabilities is the registry's job later.
"""
from __future__ import annotations

from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from app.dal.base import DuplicateError, latest_active, sort_by_semver_desc, stamp_new
from app.db.mongo import PROCESS_PACKS
from app.models.process_pack import ProcessPackManifest

_MANIFEST_PROJECTION = {"_id": 0, "bpmn_xml": 0}


def _to_manifest(doc: dict) -> ProcessPackManifest:
    return ProcessPackManifest.model_validate(doc)


class ProcessPackRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def insert(self, manifest: ProcessPackManifest, bpmn_xml: str) -> ProcessPackManifest:
        doc = stamp_new(manifest.to_doc())
        doc["bpmn_xml"] = bpmn_xml
        try:
            await self._coll.insert_one(doc)
        except DuplicateKeyError:
            raise DuplicateError(f"pack {manifest.pack_key}@{manifest.version}")
        doc.pop("_id", None)
        doc.pop("bpmn_xml", None)
        return _to_manifest(doc)

    async def get(self, pack_key: str, version: str) -> Optional[ProcessPackManifest]:
        doc = await self._coll.find_one(
            {"pack_key": pack_key, "version": version}, projection=_MANIFEST_PROJECTION
        )
        return _to_manifest(doc) if doc else None

    async def get_bpmn(self, pack_key: str, version: str) -> Optional[str]:
        doc = await self._coll.find_one(
            {"pack_key": pack_key, "version": version}, projection={"_id": 0, "bpmn_xml": 1}
        )
        return doc.get("bpmn_xml") if doc else None

    async def get_raw(self, pack_key: str, version: str) -> Optional[dict]:
        """Full stored doc (incl. bpmn_xml, timestamps) for idempotency checks."""
        return await self._coll.find_one(
            {"pack_key": pack_key, "version": version}, projection={"_id": 0}
        )

    async def list_versions(self, pack_key: str) -> List[ProcessPackManifest]:
        cursor = self._coll.find({"pack_key": pack_key}, projection=_MANIFEST_PROJECTION)
        items = [_to_manifest(d) async for d in cursor]
        return sort_by_semver_desc(items)

    async def get_latest_active(self, pack_key: str) -> Optional[ProcessPackManifest]:
        return latest_active(await self.list_versions(pack_key))

    async def list(
        self,
        *,
        status: Optional[str] = None,
        tenant_scope: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ProcessPackManifest]:
        query: dict = {}
        if status:
            query["status"] = status
        if tenant_scope:
            query["tenant_scope"] = tenant_scope
        cursor = (
            self._coll.find(query, projection=_MANIFEST_PROJECTION)
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return [_to_manifest(d) async for d in cursor]
