# app/routers/packs.py
"""ProcessPack read/inspection API."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.dal.pack_repo import ProcessPackRepository
from app.deps import get_pack_repo
from app.models.process_pack import ProcessPackManifest

router = APIRouter(prefix="/packs", tags=["packs"])


@router.get("", response_model=List[ProcessPackManifest])
async def list_packs(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: ProcessPackRepository = Depends(get_pack_repo),
):
    return await repo.list(status=status, limit=limit, offset=offset)


@router.get("/{pack_key}", response_model=List[ProcessPackManifest])
async def list_pack_versions(pack_key: str, repo: ProcessPackRepository = Depends(get_pack_repo)):
    versions = await repo.list_versions(pack_key)
    if not versions:
        raise HTTPException(status_code=404, detail=f"Unknown pack: {pack_key}")
    return versions


@router.get("/{pack_key}/{version}", response_model=ProcessPackManifest)
async def get_pack(pack_key: str, version: str, repo: ProcessPackRepository = Depends(get_pack_repo)):
    manifest = await repo.get(pack_key, version)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Unknown pack {pack_key}@{version}")
    return manifest


@router.get("/{pack_key}/{version}/bpmn")
async def get_pack_bpmn(pack_key: str, version: str, repo: ProcessPackRepository = Depends(get_pack_repo)):
    bpmn = await repo.get_bpmn(pack_key, version)
    if bpmn is None:
        raise HTTPException(status_code=404, detail=f"Unknown pack {pack_key}@{version}")
    return Response(content=bpmn, media_type="application/xml")
