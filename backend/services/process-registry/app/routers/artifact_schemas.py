# app/routers/artifact_schemas.py
"""Artifact schema registration (via the shared pipeline) + read + deprecate.

ADR-060: schemas are pack-owned. Reads and the deprecate mutation are PACK-SCOPED — a pack can only ever see
(and act on) its own rows — so they live under ``/packs/{pack_key}/{pack_version}/artifact-schemas/...``.
Registration (POST) takes ownership from the registration body (which carries ``pack_key``/``pack_version``);
the browse list (``GET /artifact-schemas``) returns all owned rows across packs.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from amendia_auth import require_roles

from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.base import DuplicateError
from app.deps import get_artifact_schema_repo
from app.services.registration import RegistrationError, register_schema

router = APIRouter(prefix="/artifact-schemas", tags=["artifact-schemas"])
# ADR-060: pack-scoped reads/mutations.
pack_router = APIRouter(prefix="/packs/{pack_key}/{pack_version}/artifact-schemas", tags=["artifact-schemas"])

_OWNER = Depends(require_roles("role.process.owner"))


@router.post("", response_model=ArtifactSchemaRegistration, status_code=201, dependencies=[_OWNER])
async def register_artifact_schema(
    reg: ArtifactSchemaRegistration, repo: ArtifactSchemaRepository = Depends(get_artifact_schema_repo)
):
    try:
        return await register_schema(reg, repo)
    except RegistrationError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors, "warnings": exc.warnings})
    except DuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("", response_model=List[ArtifactSchemaRegistration])
async def list_artifact_schemas(
    pack_key: Optional[str] = Query(None),
    pack_version: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: ArtifactSchemaRepository = Depends(get_artifact_schema_repo),
):
    # ADR-060: all owned rows; optionally narrowed to one pack via the query params.
    return await repo.list(pack_key=pack_key, pack_version=pack_version,
                           status=status, limit=limit, offset=offset)


@pack_router.get("", response_model=List[ArtifactSchemaRegistration])
async def list_pack_artifact_schemas(
    pack_key: str, pack_version: str,
    repo: ArtifactSchemaRepository = Depends(get_artifact_schema_repo),
):
    """ADR-060 D3 / ADR-061 Phase 4: every artifact schema THIS pack version owns, reached structurally."""
    return await repo.list_owned(pack_key, pack_version)


@pack_router.get("/{artifact_key}", response_model=List[ArtifactSchemaRegistration])
async def list_artifact_schema_versions(
    pack_key: str, pack_version: str, artifact_key: str,
    repo: ArtifactSchemaRepository = Depends(get_artifact_schema_repo),
):
    versions = await repo.list_by_key(pack_key, pack_version, artifact_key)
    if not versions:
        raise HTTPException(status_code=404,
                            detail=f"Unknown artifact schema {artifact_key} for pack {pack_key}@{pack_version}")
    return versions


@pack_router.get("/{artifact_key}/{version}", response_model=ArtifactSchemaRegistration)
async def get_artifact_schema(
    pack_key: str, pack_version: str, artifact_key: str, version: str,
    repo: ArtifactSchemaRepository = Depends(get_artifact_schema_repo),
):
    reg = await repo.get(pack_key, pack_version, artifact_key, version)
    if reg is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown artifact schema {artifact_key}@{version} for pack {pack_key}@{pack_version}")
    return reg


@pack_router.post("/{artifact_key}/{version}/deprecate", response_model=ArtifactSchemaRegistration,
                  dependencies=[_OWNER])
async def deprecate_artifact_schema(
    pack_key: str, pack_version: str, artifact_key: str, version: str,
    repo: ArtifactSchemaRepository = Depends(get_artifact_schema_repo),
):
    reg = await repo.set_status(pack_key, pack_version, artifact_key, version, "deprecated")
    if reg is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown artifact schema {artifact_key}@{version} for pack {pack_key}@{pack_version}")
    return reg
