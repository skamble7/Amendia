# app/dal/instance_repo.py
"""Process-instance repository (runtime-owned aggregate)."""
from __future__ import annotations

from typing import Iterable, List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.dal.base import DuplicateError
from app.models.common import utcnow
from app.models.process_instance import InstanceStatus, ProcessInstance

_PROJECTION = {"_id": 0}


class ProcessInstanceRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def insert(self, instance: ProcessInstance) -> ProcessInstance:
        try:
            await self._coll.insert_one(instance.to_doc())
        except DuplicateKeyError:
            raise DuplicateError(f"process instance {instance.process_instance_id}")
        return instance

    async def get(self, process_instance_id: str) -> Optional[ProcessInstance]:
        doc = await self._coll.find_one(
            {"process_instance_id": process_instance_id}, projection=_PROJECTION
        )
        return ProcessInstance.model_validate(doc) if doc else None

    async def get_by_idempotency_key(self, idempotency_key: str) -> Optional[ProcessInstance]:
        doc = await self._coll.find_one({"idempotency_key": idempotency_key}, projection=_PROJECTION)
        return ProcessInstance.model_validate(doc) if doc else None

    async def list(
        self,
        *,
        tenant: Optional[str] = None,
        exception_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ProcessInstance]:
        query: dict = {}
        if tenant:
            query["tenant"] = tenant
        if exception_id:
            query["exception_id"] = exception_id
        if status:
            query["status"] = status
        cursor = (
            self._coll.find(query, projection=_PROJECTION)
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return [ProcessInstance.model_validate(d) async for d in cursor]

    async def list_by_status(self, status: InstanceStatus, *, limit: int = 200) -> List[ProcessInstance]:
        cursor = self._coll.find({"status": status.value}, projection=_PROJECTION).limit(limit)
        return [ProcessInstance.model_validate(d) async for d in cursor]

    async def set_status(
        self,
        process_instance_id: str,
        status: InstanceStatus,
        *,
        expected: Optional[Iterable[InstanceStatus]] = None,
        **fields,
    ) -> Optional[ProcessInstance]:
        """Guarded status update. If ``expected`` is given, only transitions from
        one of those states (returns None otherwise)."""
        query: dict = {"process_instance_id": process_instance_id}
        if expected is not None:
            query["status"] = {"$in": [s.value for s in expected]}
        update = {"status": status.value, "updated_at": utcnow().isoformat(), **fields}
        # NB: no projection kwarg — mongomock-motor mishandles projection + AFTER together.
        doc = await self._coll.find_one_and_update(
            query, {"$set": update}, return_document=ReturnDocument.AFTER
        )
        if doc is None:
            return None
        doc.pop("_id", None)
        return ProcessInstance.model_validate(doc)

    async def update_fields(self, process_instance_id: str, **fields) -> Optional[ProcessInstance]:
        update = {"updated_at": utcnow().isoformat(), **fields}
        doc = await self._coll.find_one_and_update(
            {"process_instance_id": process_instance_id}, {"$set": update},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        doc.pop("_id", None)
        return ProcessInstance.model_validate(doc)
