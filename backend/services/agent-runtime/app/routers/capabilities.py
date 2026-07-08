# app/routers/capabilities.py
"""Capability descriptor read/inspection API."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dal.capability_repo import CapabilityRepository
from app.deps import get_capability_repo
from app.models.capability import CapabilityDescriptor

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("", response_model=List[CapabilityDescriptor])
async def list_capabilities(
    status: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: CapabilityRepository = Depends(get_capability_repo),
):
    return await repo.list(status=status, kind=kind, limit=limit, offset=offset)


@router.get("/{capability_id}", response_model=List[CapabilityDescriptor])
async def list_capability_versions(
    capability_id: str, repo: CapabilityRepository = Depends(get_capability_repo)
):
    versions = await repo.list_versions(capability_id)
    if not versions:
        raise HTTPException(status_code=404, detail=f"Unknown capability: {capability_id}")
    return versions


@router.get("/{capability_id}/{version}", response_model=CapabilityDescriptor)
async def get_capability(
    capability_id: str, version: str, repo: CapabilityRepository = Depends(get_capability_repo)
):
    cap = await repo.get(capability_id, version)
    if cap is None:
        raise HTTPException(status_code=404, detail=f"Unknown capability {capability_id}@{version}")
    return cap
