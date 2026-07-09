# app/routers/capabilities.py
"""Capability registration + read + deprecate."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from amendia_auth import require_roles

from amendia_contracts.capability import CapabilityDescriptor
from app.dal.base import DuplicateError
from app.dal.capability_repo import CapabilityRepository
from app.deps import get_capability_repo

router = APIRouter(prefix="/capabilities", tags=["capabilities"])

_OWNER = Depends(require_roles("role.process.owner"))


@router.post("", response_model=CapabilityDescriptor, status_code=201, dependencies=[_OWNER])
async def register_capability(
    cap: CapabilityDescriptor, repo: CapabilityRepository = Depends(get_capability_repo)
):
    # runtime.kind == kind is enforced by the model; the model validation already ran.
    try:
        return await repo.insert(cap)
    except DuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


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
    versions = await repo.list_by_id(capability_id)
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


@router.post("/{capability_id}/{version}/deprecate", response_model=CapabilityDescriptor, dependencies=[_OWNER])
async def deprecate_capability(
    capability_id: str, version: str, repo: CapabilityRepository = Depends(get_capability_repo)
):
    cap = await repo.set_status(capability_id, version, "deprecated")
    if cap is None:
        raise HTTPException(status_code=404, detail=f"Unknown capability {capability_id}@{version}")
    return cap
