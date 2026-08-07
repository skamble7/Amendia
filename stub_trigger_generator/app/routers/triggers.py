# app/routers/triggers.py
"""Trigger store surface (ADR-059 D2): list, fetch-back the clean domain payload, and serve attachment
bytes. Domain-blind — one collection, no per-domain routes. Generation lives in ``routers/generators.py``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.dal.trigger_repo import TriggerRepository
from app.deps import get_repo
from app.models.trigger import StoredTrigger
from app.sample_data import CATALOG, read_bytes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triggers", tags=["triggers"])


@router.get("", response_model=List[StoredTrigger])
async def list_triggers(
    trigger_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: TriggerRepository = Depends(get_repo),
):
    return await repo.list(trigger_type=trigger_type, status=status, limit=limit, offset=offset)


@router.get("/{trigger_id}")
async def get_trigger(trigger_id: str, repo: TriggerRepository = Depends(get_repo)) -> Dict[str, Any]:
    """Fetch-back: return the CLEAN domain payload (ADR-047 D1) — not the stored row. The pack's declared
    trigger schema is ``additionalProperties: false``, so the fetched trigger must be exactly the domain
    envelope with no store metadata. Uniform across every domain (the wire path previously returned the row
    with metadata; it now matches the dine path)."""
    stored = await repo.get(trigger_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Unknown trigger_id: {trigger_id}")
    return stored.payload


@router.get("/{trigger_id}/attachments/{attachment_id}")
async def get_attachment(
    trigger_id: str,
    attachment_id: str,
    repo: TriggerRepository = Depends(get_repo),
):
    stored = await repo.get(trigger_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Unknown trigger_id: {trigger_id}")

    attachments = stored.payload.get("attachments") or []
    att = next((a for a in attachments if a.get("attachment_id") == attachment_id), None)
    if att is None or attachment_id not in CATALOG:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown attachment '{attachment_id}' on trigger {trigger_id}",
        )
    return Response(content=read_bytes(attachment_id), media_type=att.get("media_type"))
