# app/routers/instances.py
"""Process-instance read API + a flag-guarded checkpoint-state debug surface."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import settings
from app.dal.hitl_task_repo import HitlTaskRepository
from app.dal.instance_repo import ProcessInstanceRepository
from app.deps import get_engine, get_hitl_task_repo, get_instance_repo
from app.models.process_instance import ProcessInstance

router = APIRouter(prefix="/instances", tags=["instances"])


@router.get("", response_model=List[ProcessInstance])
async def list_instances(
    tenant: Optional[str] = Query(None),
    exception_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: ProcessInstanceRepository = Depends(get_instance_repo),
):
    return await repo.list(
        tenant=tenant, exception_id=exception_id, status=status, limit=limit, offset=offset
    )


@router.get("/{process_instance_id}")
async def get_instance(
    process_instance_id: str,
    repo: ProcessInstanceRepository = Depends(get_instance_repo),
    hitl_repo: HitlTaskRepository = Depends(get_hitl_task_repo),
    engine=Depends(get_engine),
):
    inst = await repo.get(process_instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail=f"Unknown instance: {process_instance_id}")
    tasks = await hitl_repo.list(process_instance_id=process_instance_id, limit=200)
    actor_log = []
    if engine is not None:
        try:
            state = await engine.get_checkpoint_state(
                process_instance_id, inst.pack_key, inst.pack_version
            )
            actor_log = state.get("actor_log", [])
        except Exception:  # noqa: BLE001 - best-effort enrichment
            actor_log = []
    return {
        "instance": inst.model_dump(mode="json"),
        "status": inst.status.value,
        "outcome": inst.outcome,
        "artifact_names": inst.artifact_names,
        "actor_log": actor_log,
        "hitl_tasks": [
            {"task_id": t.task_id, "element_id": t.element_id, "status": t.status.value,
             "hitl_mode": t.hitl_mode.value, "role": t.role}
            for t in tasks
        ],
    }


@router.get("/{process_instance_id}/state")
async def get_instance_state(
    process_instance_id: str,
    repo: ProcessInstanceRepository = Depends(get_instance_repo),
    engine=Depends(get_engine),
):
    """The current checkpointed graph state (artifacts included) — dev/debug only."""
    if not settings.ENABLE_DEBUG_API:
        raise HTTPException(status_code=404, detail="debug API disabled")
    inst = await repo.get(process_instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail=f"Unknown instance: {process_instance_id}")
    if engine is None:
        raise HTTPException(status_code=503, detail="engine not available")
    state = await engine.get_checkpoint_state(
        process_instance_id, inst.pack_key, inst.pack_version
    )
    return {
        "process_instance_id": process_instance_id,
        "status": inst.status.value,
        "outcome": inst.outcome,
        "artifacts": state.get("artifacts", {}),
        "actor_log": state.get("actor_log", []),
        "trace": state.get("trace", {}),
        "last_error": state.get("last_error"),
    }
