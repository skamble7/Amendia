# app/routers/capabilities.py
"""Capability registration + read + deprecate.

ADR-060: capabilities are pack-owned. Reads and the deprecate mutation are PACK-SCOPED — a pack can only
ever see (and act on) its own rows — so they live under ``/packs/{pack_key}/{pack_version}/capabilities/...``.
Registration (POST) takes ownership from the descriptor body (which carries ``pack_key``/``pack_version``);
the browse list (``GET /capabilities``) returns all owned rows across packs.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from amendia_auth import require_roles

from amendia_contracts.capability import CapabilityDescriptor
from app.dal.base import DuplicateError
from app.dal.capability_repo import CapabilityRepository
from app.deps import get_capability_repo

router = APIRouter(prefix="/capabilities", tags=["capabilities"])
# ADR-060: pack-scoped reads/mutations — the owning pack coordinates are structural, not a query bolt-on.
pack_router = APIRouter(prefix="/packs/{pack_key}/{pack_version}/capabilities", tags=["capabilities"])

_OWNER = Depends(require_roles("role.process.owner"))


@router.post("", response_model=CapabilityDescriptor, status_code=201, dependencies=[_OWNER])
async def register_capability(
    cap: CapabilityDescriptor, repo: CapabilityRepository = Depends(get_capability_repo)
):
    # runtime.kind == kind is enforced by the model; ownership (pack_key/pack_version) travels on the body.
    try:
        return await repo.insert(cap)
    except DuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("", response_model=List[CapabilityDescriptor])
async def list_capabilities(
    pack_key: Optional[str] = Query(None),
    pack_version: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="free-text substring over capability_id + title"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: CapabilityRepository = Depends(get_capability_repo),
):
    # ADR-060: all owned rows; optionally narrowed to one pack via the query params.
    return await repo.list(pack_key=pack_key, pack_version=pack_version,
                           status=status, kind=kind, q=q, limit=limit, offset=offset)


@pack_router.get("", response_model=List[CapabilityDescriptor])
async def list_pack_capabilities(
    pack_key: str, pack_version: str,
    repo: CapabilityRepository = Depends(get_capability_repo),
):
    """ADR-060 D3 / ADR-061 Phase 4: every capability THIS pack version owns, reached structurally (not a
    query-param browse). The empty catalog is a valid 200 — an empty list."""
    return await repo.list_owned(pack_key, pack_version)


@pack_router.get("/{capability_id}", response_model=List[CapabilityDescriptor])
async def list_capability_versions(
    pack_key: str, pack_version: str, capability_id: str,
    repo: CapabilityRepository = Depends(get_capability_repo),
):
    versions = await repo.list_by_id(pack_key, pack_version, capability_id)
    if not versions:
        raise HTTPException(status_code=404,
                            detail=f"Unknown capability {capability_id} for pack {pack_key}@{pack_version}")
    return versions


@pack_router.get("/{capability_id}/{version}", response_model=CapabilityDescriptor)
async def get_capability(
    pack_key: str, pack_version: str, capability_id: str, version: str,
    repo: CapabilityRepository = Depends(get_capability_repo),
):
    cap = await repo.get(pack_key, pack_version, capability_id, version)
    if cap is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown capability {capability_id}@{version} for pack {pack_key}@{pack_version}")
    return cap


@pack_router.post("/{capability_id}/{version}/deprecate", response_model=CapabilityDescriptor,
                  dependencies=[_OWNER])
async def deprecate_capability(
    pack_key: str, pack_version: str, capability_id: str, version: str,
    repo: CapabilityRepository = Depends(get_capability_repo),
):
    cap = await repo.set_status(pack_key, pack_version, capability_id, version, "deprecated")
    if cap is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown capability {capability_id}@{version} for pack {pack_key}@{pack_version}")
    return cap
