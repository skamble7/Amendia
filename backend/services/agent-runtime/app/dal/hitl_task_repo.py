# app/dal/hitl_task_repo.py
"""HITL task repository — read surface + a guarded status transition (for later)."""
from __future__ import annotations

from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.dal.base import DuplicateError
from app.models.common import utcnow
from app.models.hitl_task import HitlTask, TaskStatus

_PROJECTION = {"_id": 0}


class HitlTaskRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def insert(self, task: HitlTask) -> HitlTask:
        doc = task.to_doc()
        doc["updated_at"] = utcnow().isoformat()
        try:
            await self._coll.insert_one(doc)
        except DuplicateKeyError:
            raise DuplicateError(f"hitl task {task.task_id}")
        doc.pop("_id", None)
        return HitlTask.model_validate(doc)

    async def get(self, task_id: str) -> Optional[HitlTask]:
        doc = await self._coll.find_one({"task_id": task_id}, projection=_PROJECTION)
        return HitlTask.model_validate(doc) if doc else None

    async def list(
        self,
        *,
        tenant: Optional[str] = None,
        status: Optional[str] = None,
        role: Optional[str] = None,
        process_instance_id: Optional[str] = None,
        exception_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[HitlTask]:
        query: dict = {}
        if tenant:
            query["tenant"] = tenant
        if status:
            query["status"] = status
        if role:
            query["role"] = role
        if process_instance_id:
            query["process_instance_id"] = process_instance_id
        if exception_id:
            query["exception_id"] = exception_id
        cursor = (
            self._coll.find(query, projection=_PROJECTION)
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return [HitlTask.model_validate(d) async for d in cursor]

    async def transition_status(
        self,
        task_id: str,
        *,
        expected_status: TaskStatus,
        new_status: TaskStatus,
        set_fields: Optional[dict] = None,
    ) -> Optional[HitlTask]:
        """Guarded transition: only applies if the task is in ``expected_status``.

        Returns the updated task, or None if the guard did not match. (Not called
        in this slice — the decision/resume API belongs to the execution step.)
        """
        update = {"status": new_status.value, "updated_at": utcnow().isoformat()}
        if set_fields:
            update.update(set_fields)
        # NB: no projection kwarg — mongomock-motor mishandles projection + AFTER together.
        doc = await self._coll.find_one_and_update(
            {"task_id": task_id, "status": expected_status.value},
            {"$set": update},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        doc.pop("_id", None)
        return HitlTask.model_validate(doc)
