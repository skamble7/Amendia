# app/routers/ingestions.py
"""Read API over the ingestion log (the processed exceptions)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dal.ingestion_repo import IngestionRepository
from app.deps import get_repo
from app.models.ingestion import IngestionRecord

router = APIRouter(prefix="/ingestions", tags=["ingestions"])


@router.get("", response_model=list[IngestionRecord])
async def list_ingestions(
    tenant: Optional[str] = Query(None),
    exception_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: IngestionRepository = Depends(get_repo),
):
    return await repo.list(
        tenant=tenant,
        exception_type=exception_type,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/{exception_id}", response_model=IngestionRecord)
async def get_ingestion(exception_id: str, repo: IngestionRepository = Depends(get_repo)):
    record = await repo.get(exception_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No ingestion for exception_id: {exception_id}")
    return record
