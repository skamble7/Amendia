# app/routers/artifact_schemas.py
"""Artifact schema registration (via the shared pipeline) + read + deprecate."""
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
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: ArtifactSchemaRepository = Depends(get_artifact_schema_repo),
):
    return await repo.list(status=status, limit=limit, offset=offset)


@router.get("/{artifact_key}", response_model=List[ArtifactSchemaRegistration])
async def list_artifact_schema_versions(
    artifact_key: str, repo: ArtifactSchemaRepository = Depends(get_artifact_schema_repo)
):
    versions = await repo.list_by_key(artifact_key)
    if not versions:
        raise HTTPException(status_code=404, detail=f"Unknown artifact schema: {artifact_key}")
    return versions


@router.get("/{artifact_key}/{version}", response_model=ArtifactSchemaRegistration)
async def get_artifact_schema(
    artifact_key: str, version: str, repo: ArtifactSchemaRepository = Depends(get_artifact_schema_repo)
):
    reg = await repo.get(artifact_key, version)
    if reg is None:
        raise HTTPException(status_code=404, detail=f"Unknown artifact schema {artifact_key}@{version}")
    return reg


@router.post("/{artifact_key}/{version}/deprecate", response_model=ArtifactSchemaRegistration, dependencies=[_OWNER])
async def deprecate_artifact_schema(
    artifact_key: str, version: str, repo: ArtifactSchemaRepository = Depends(get_artifact_schema_repo)
):
    reg = await repo.set_status(artifact_key, version, "deprecated")
    if reg is None:
        raise HTTPException(status_code=404, detail=f"Unknown artifact schema {artifact_key}@{version}")
    return reg
