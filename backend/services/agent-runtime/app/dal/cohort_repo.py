# app/dal/cohort_repo.py
"""ADR-063 Phase 1 — cohort-instance repository (runtime SoR).

Identity/dedup is by ``correlation_value`` alone (unique index). Get-or-create is a single atomic
``find_one_and_update(..., upsert=True)`` — first-writer-wins, never a racy app-level check-then-insert.
Member ops are idempotent (a checkpoint-restarted segment must not double-register, and its count must not
double-count).
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.models.cohort_instance import CohortInstance, CohortState
from app.models.common import utcnow

_PROJECTION = {"_id": 0}


def _new_cohort_id() -> str:
    return f"coh-{uuid.uuid4().hex[:12]}"


class CohortInstanceRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def get_by_correlation_value(self, correlation_value: str) -> Optional[CohortInstance]:
        doc = await self._coll.find_one({"correlation_value": correlation_value}, projection=_PROJECTION)
        return CohortInstance.model_validate(doc) if doc else None

    async def get(self, cohort_instance_id: str) -> Optional[CohortInstance]:
        doc = await self._coll.find_one({"cohort_instance_id": cohort_instance_id}, projection=_PROJECTION)
        return CohortInstance.model_validate(doc) if doc else None

    async def get_or_open(self, correlation_value: str, cohort_def_id: str) -> Tuple[CohortInstance, bool]:
        """Atomically fetch the cohort for ``correlation_value`` or open a fresh ``open`` one, first-writer-wins.
        Returns ``(cohort, created)``. Creation is detected by whether OUR candidate id survived the
        ``$setOnInsert`` — an existing row keeps its own id. A concurrent upsert that loses the unique-index
        race raises ``DuplicateKeyError``; we then simply read the winner's row (created=False)."""
        candidate_id = _new_cohort_id()
        now = utcnow().isoformat()
        try:
            doc = await self._coll.find_one_and_update(
                {"correlation_value": correlation_value},
                {"$setOnInsert": {
                    "cohort_instance_id": candidate_id,
                    "correlation_value": correlation_value,
                    "cohort_def_id": cohort_def_id,
                    "state": CohortState.OPEN.value,
                    "members": [],
                    "active_member_count": 0,
                    "opened_at": now,
                    "updated_at": now,
                    "closed_at": None,
                    "close_outcome": None,
                }},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            existing = await self.get_by_correlation_value(correlation_value)
            if existing is None:  # pragma: no cover - defensive; the winner's row must exist
                raise
            return existing, False
        doc.pop("_id", None)
        created = doc.get("cohort_instance_id") == candidate_id
        return CohortInstance.model_validate(doc), created

    async def set_sla_snapshot(self, cohort_instance_id: str, snapshot: Dict[str, Any]) -> None:
        """ADR-064 P2: stamp the definition's ``expectation_graph`` onto the cohort at OPEN (forward-only).
        Guarded ``$eq: None`` so it is written once by the opener and a re-attempt never overwrites — a mid-
        flight cohort keeps the expectations it opened under."""
        await self._coll.update_one(
            {"cohort_instance_id": cohort_instance_id, "expectation_graph_snapshot": None},
            {"$set": {"expectation_graph_snapshot": snapshot, "updated_at": utcnow().isoformat()}},
        )

    async def add_member(self, cohort_instance_id: str, process_instance_id: str, pack_key: str) -> bool:
        """Idempotently attach a member. Returns True if newly added, False if already on the roster. The
        ``$ne`` guard makes the push + count-increment atomic AND idempotent: a re-join finds no matching
        (id, member-absent) doc → no update → False, so the count never double-counts."""
        doc = await self._coll.find_one_and_update(
            {"cohort_instance_id": cohort_instance_id,
             "members.process_instance_id": {"$ne": process_instance_id}},
            {"$push": {"members": {
                "process_instance_id": process_instance_id, "pack_key": pack_key, "terminal": False}},
             "$inc": {"active_member_count": 1},
             "$set": {"updated_at": utcnow().isoformat()}},
            return_document=ReturnDocument.AFTER,
        )
        return doc is not None

    async def begin_close(self, correlation_value: str, close_outcome: Optional[str]) -> Optional[CohortInstance]:
        """ADR-063 Phase 2: `open → closing`, atomic + idempotent. Matches only an OPEN cohort for the value, so
        a duplicate close (already closing/closed) matches nothing → None (idempotent no-op). Returns the CLOSING
        cohort on success."""
        doc = await self._coll.find_one_and_update(
            {"correlation_value": correlation_value, "state": CohortState.OPEN.value},
            {"$set": {"state": CohortState.CLOSING.value, "close_outcome": close_outcome,
                      "updated_at": utcnow().isoformat()}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        doc.pop("_id", None)
        return CohortInstance.model_validate(doc)

    async def finalize_if_drained(self, cohort_instance_id: str) -> Optional[CohortInstance]:
        """ADR-063 Phase 2: `closing → closed`, atomic. The **single** conditional both the close path and the
        last member-terminal drain run — only one `find_one_and_update` can match `{state: CLOSING,
        active_member_count: 0}`, so exactly one caller finalizes (→ exactly one `closed`). Returns the CLOSED
        cohort on the winning call, else None."""
        doc = await self._coll.find_one_and_update(
            {"cohort_instance_id": cohort_instance_id, "state": CohortState.CLOSING.value,
             "active_member_count": 0},
            {"$set": {"state": CohortState.CLOSED.value, "closed_at": utcnow().isoformat(),
                      "updated_at": utcnow().isoformat()}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        doc.pop("_id", None)
        return CohortInstance.model_validate(doc)

    async def mark_member_terminal(self, cohort_instance_id: str, process_instance_id: str) -> Optional[CohortInstance]:
        """Idempotently flip a member's ``terminal`` flag and decrement ``active_member_count``. Matches only a
        non-terminal member (``$elemMatch``), so a re-drain (crash replay) is a no-op that never under-counts.
        Returns the updated cohort, or None when nothing changed (already terminal / unknown member)."""
        doc = await self._coll.find_one_and_update(
            {"cohort_instance_id": cohort_instance_id,
             "members": {"$elemMatch": {"process_instance_id": process_instance_id, "terminal": False}}},
            {"$set": {"members.$.terminal": True, "updated_at": utcnow().isoformat()},
             "$inc": {"active_member_count": -1}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        doc.pop("_id", None)
        return CohortInstance.model_validate(doc)
