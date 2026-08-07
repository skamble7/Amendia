# app/routers/ingestions.py
"""Read API over the ingestion log (the processed triggers)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dal.ingestion_repo import IngestionRepository
from app.deps import get_repo
from app.models.ingestion import IngestionRecord

router = APIRouter(prefix="/ingestions", tags=["ingestions"])


@router.get("", response_model=list[IngestionRecord])
async def list_ingestions(
    trigger_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: IngestionRepository = Depends(get_repo),
):
    return await repo.list(
        trigger_type=trigger_type,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/{trigger_id}", response_model=IngestionRecord)
async def get_ingestion(trigger_id: str, repo: IngestionRepository = Depends(get_repo)):
    record = await repo.get(trigger_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No ingestion for trigger_id: {trigger_id}")
    return record
