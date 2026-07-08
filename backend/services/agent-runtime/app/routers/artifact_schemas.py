# app/routers/artifact_schemas.py
"""Artifact schema registry read/inspection API."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.deps import get_artifact_schema_repo
from app.models.artifact_schema import ArtifactSchemaRegistration

router = APIRouter(prefix="/artifact-schemas", tags=["artifact-schemas"])


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
    versions = await repo.list_versions(artifact_key)
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
