# app/dal/pack_repo.py
"""ProcessPack repository.

The ``process_packs`` doc stays a **pure manifest** (same shape the agent-runtime reads):
manifest fields + store timestamps + ``requires_capabilities[].resolved`` pins. Registry-only
data — the validation report and the full activation ``resolution`` — lives in sidecar
collections so it never changes the shared doc's shape. The runtime's ``bpmn_xml`` field (it
stores BPMN inline) is tolerated on read.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from amendia_contracts.process_pack import ProcessPackManifest
from app.dal.base import DuplicateError, stamp_new, utcnow_iso

# Exclude Mongo _id and the runtime-only bpmn_xml so the doc validates as a manifest.
_MANIFEST_PROJECTION = {"_id": 0, "bpmn_xml": 0}


def _to_manifest(doc: dict) -> ProcessPackManifest:
    clean = {k: v for k, v in doc.items() if k not in ("_id", "bpmn_xml")}
    return ProcessPackManifest.model_validate(clean)


class ProcessPackRepository:
    def __init__(
        self,
        collection: AsyncIOMotorCollection,
        reports: Optional[AsyncIOMotorCollection] = None,
        resolutions: Optional[AsyncIOMotorCollection] = None,
    ) -> None:
        self._coll = collection
        self._reports = reports
        self._resolutions = resolutions

    async def insert(self, manifest: ProcessPackManifest) -> ProcessPackManifest:
        doc = stamp_new(manifest.to_doc())
        try:
            await self._coll.insert_one(doc)
        except DuplicateKeyError:
            raise DuplicateError(f"pack {manifest.pack_key}@{manifest.version}")
        doc.pop("_id", None)
        return _to_manifest(doc)

    async def get(self, pack_key: str, version: str) -> Optional[ProcessPackManifest]:
        doc = await self._coll.find_one(
            {"pack_key": pack_key, "version": version}, projection=_MANIFEST_PROJECTION
        )
        return _to_manifest(doc) if doc else None

    async def get_raw(self, pack_key: str, version: str) -> Optional[dict]:
        return await self._coll.find_one({"pack_key": pack_key, "version": version}, projection={"_id": 0})

    async def list_versions(self, pack_key: str) -> List[ProcessPackManifest]:
        cursor = self._coll.find({"pack_key": pack_key}, projection=_MANIFEST_PROJECTION)
        return [_to_manifest(d) async for d in cursor]

    async def list(
        self, *, status: Optional[str] = None, tenant_scope: Optional[str] = None,
        limit: int = 50, offset: int = 0,
    ) -> List[ProcessPackManifest]:
        query: dict = {}
        if status:
            query["status"] = status
        if tenant_scope:
            query["tenant_scope"] = tenant_scope
        cursor = (
            self._coll.find(query, projection=_MANIFEST_PROJECTION)
            .sort("created_at", -1).skip(offset).limit(limit)
        )
        return [_to_manifest(d) async for d in cursor]

    async def list_active_raw(self) -> List[dict]:
        cursor = self._coll.find({"status": "active"}, projection={"_id": 0, "bpmn_xml": 0})
        return [d async for d in cursor]

    # -- lifecycle mutations --
    async def set_status(self, pack_key: str, version: str, status: str) -> None:
        await self._coll.update_one(
            {"pack_key": pack_key, "version": version},
            {"$set": {"status": status, "updated_at": utcnow_iso()}},
        )

    async def set_bpmn_sha(self, pack_key: str, version: str, sha256: str) -> None:
        await self._coll.update_one(
            {"pack_key": pack_key, "version": version},
            {"$set": {"process.bpmn_sha256": sha256, "status": "draft", "updated_at": utcnow_iso()}},
        )

    async def activate(
        self, pack_key: str, version: str, *,
        resolved_caps: Dict[str, str], resolution: Dict[str, Any],
    ) -> Optional[ProcessPackManifest]:
        raw = await self.get_raw(pack_key, version)
        if raw is None:
            return None
        for rc in raw.get("requires_capabilities", []):
            cap_id = rc.get("ref", "").split("@", 1)[0]
            if cap_id in resolved_caps:
                rc["resolved"] = f"{cap_id}@{resolved_caps[cap_id]}"
        doc = await self._coll.find_one_and_update(
            {"pack_key": pack_key, "version": version},
            {"$set": {
                "requires_capabilities": raw["requires_capabilities"],
                "status": "active",
                "updated_at": utcnow_iso(),
            }},
            projection=_MANIFEST_PROJECTION, return_document=ReturnDocument.AFTER,
        )
        if self._resolutions is not None:
            await self._resolutions.replace_one(
                {"pack_key": pack_key, "version": version},
                {"pack_key": pack_key, "version": version, **resolution},
                upsert=True,
            )
        return _to_manifest(doc) if doc else None

    # -- registry-only sidecars --
    async def save_validation_report(self, pack_key: str, version: str, report: Dict[str, Any]) -> None:
        if self._reports is None:
            return
        await self._reports.replace_one(
            {"pack_key": pack_key, "version": version},
            {"pack_key": pack_key, "version": version, "report": report},
            upsert=True,
        )

    async def get_validation_report(self, pack_key: str, version: str) -> Optional[dict]:
        if self._reports is None:
            return None
        doc = await self._reports.find_one({"pack_key": pack_key, "version": version}, projection={"_id": 0})
        return doc.get("report") if doc else None

    async def get_resolution(self, pack_key: str, version: str) -> Optional[dict]:
        if self._resolutions is None:
            return None
        doc = await self._resolutions.find_one(
            {"pack_key": pack_key, "version": version}, projection={"_id": 0, "pack_key": 0, "version": 0}
        )
        return doc if doc else None
