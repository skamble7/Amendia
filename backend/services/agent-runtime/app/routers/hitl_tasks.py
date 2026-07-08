# app/routers/hitl_tasks.py
"""HITL task API: read + claim + decide (drives interrupt/resume)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.dal.hitl_task_repo import HitlTaskRepository
from app.deps import get_hitl_service, get_hitl_task_repo
from app.models.hitl_task import HitlTask
from app.services.hitl_service import HitlDecisionService, HitlError

router = APIRouter(prefix="/hitl-tasks", tags=["hitl-tasks"])


class ClaimRequest(BaseModel):
    user_id: str
    role: Optional[str] = None


class DecideRequest(BaseModel):
    user_id: str
    decision: str
    comment: Optional[str] = None
    edits: Optional[Dict[str, Any]] = None
    approved_action_ids: Optional[List[str]] = None


@router.get("", response_model=List[HitlTask])
async def list_hitl_tasks(
    tenant: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    process_instance_id: Optional[str] = Query(None),
    exception_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: HitlTaskRepository = Depends(get_hitl_task_repo),
):
    return await repo.list(
        tenant=tenant, status=status, role=role,
        process_instance_id=process_instance_id, exception_id=exception_id,
        limit=limit, offset=offset,
    )


@router.get("/{task_id}", response_model=HitlTask)
async def get_hitl_task(task_id: str, repo: HitlTaskRepository = Depends(get_hitl_task_repo)):
    task = await repo.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Unknown task: {task_id}")
    return task


@router.post("/{task_id}/claim", response_model=HitlTask)
async def claim_task(
    task_id: str, body: ClaimRequest,
    svc: HitlDecisionService = Depends(get_hitl_service),
):
    try:
        return await svc.claim(task_id, user_id=body.user_id, role=body.role)
    except HitlError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/{task_id}/decide", response_model=HitlTask)
async def decide_task(
    task_id: str, body: DecideRequest,
    svc: HitlDecisionService = Depends(get_hitl_service),
):
    try:
        return await svc.decide(
            task_id, user_id=body.user_id, decision=body.decision, comment=body.comment,
            edits=body.edits, approved_action_ids=body.approved_action_ids,
        )
    except HitlError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
