# app/dal/role_repo.py
"""Role-assignment repository (grants + pending-by-email grants)."""
from __future__ import annotations

import re
from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from app.dal.base import DuplicateError, utcnow_iso

_PROJECTION = {"_id": 0}


class RoleRepository:
    def __init__(
        self, assignments: AsyncIOMotorCollection, pending: AsyncIOMotorCollection
    ) -> None:
        self._coll = assignments
        self._pending = pending

    async def roles_for(self, amendia_user_id: str) -> List[str]:
        cursor = self._coll.find({"amendia_user_id": amendia_user_id}, projection=_PROJECTION)
        return sorted([d["role"] async for d in cursor])

    async def user_ids_with_role(self, role: str) -> List[str]:
        cursor = self._coll.find({"role": role}, projection=_PROJECTION)
        return [d["amendia_user_id"] async for d in cursor]

    async def assignments_for(self, amendia_user_id: str) -> List[dict]:
        """Full grant docs (role + assigned_by/at) for one user, role-sorted."""
        cursor = self._coll.find({"amendia_user_id": amendia_user_id}, projection=_PROJECTION)
        rows = [
            {
                "role": d["role"],
                "assigned_by": d.get("assigned_by"),
                "assigned_at": d.get("assigned_at"),
            }
            async for d in cursor
        ]
        return sorted(rows, key=lambda r: r["role"])

    async def assign(self, amendia_user_id: str, role: str, assigned_by: str) -> None:
        doc = {
            "amendia_user_id": amendia_user_id,
            "role": role,
            "assigned_by": assigned_by,
            "assigned_at": utcnow_iso(),
        }
        try:
            await self._coll.insert_one(doc)
        except DuplicateKeyError:
            raise DuplicateError(f"role {role} on {amendia_user_id}")

    async def assign_if_absent(self, amendia_user_id: str, role: str, assigned_by: str) -> bool:
        """Idempotent grant (used when materialising pending roles). True if inserted."""
        try:
            await self.assign(amendia_user_id, role, assigned_by)
            return True
        except DuplicateError:
            return False

    async def revoke(self, amendia_user_id: str, role: str) -> bool:
        res = await self._coll.delete_one({"amendia_user_id": amendia_user_id, "role": role})
        return res.deleted_count > 0

    async def pop_assignment(self, amendia_user_id: str, role: str) -> Optional[dict]:
        """Delete and return the assignment doc (sans ``_id``), or None if absent.
        Lets the last-admin guardrail restore an over-eager revoke race-tolerantly."""
        doc = await self._coll.find_one_and_delete(
            {"amendia_user_id": amendia_user_id, "role": role}, projection=_PROJECTION
        )
        return doc

    async def restore_assignment(self, doc: dict) -> None:
        """Re-insert a popped assignment (idempotent) to roll back a refused revoke."""
        try:
            await self._coll.insert_one(dict(doc))
        except DuplicateKeyError:
            pass

    async def holders_of(self, role: str) -> List[str]:
        """User ids currently granted ``role`` (alias of ``user_ids_with_role``)."""
        return await self.user_ids_with_role(role)

    # -- pending (by email; one row per (email, role), staged before first login) --
    async def add_pending(self, email: str, role: str, staged_by: str) -> bool:
        """Idempotent single-role stage (used by the seed). True if inserted."""
        doc = {
            "email": email.lower(),
            "role": role,
            "staged_by": staged_by,
            "staged_at": utcnow_iso(),
        }
        try:
            await self._pending.insert_one(doc)
            return True
        except DuplicateKeyError:
            return False

    async def pending_roles_for_email(self, email: Optional[str]) -> List[str]:
        if not email:
            return []
        cursor = self._pending.find({"email": email.lower()}, projection=_PROJECTION)
        return [d["role"] async for d in cursor]

    async def stage_pending(self, email: str, roles: List[str], staged_by: str) -> None:
        """Add each role for ``email`` (idempotent per role). Preserves any roles
        already staged; use ``replace_pending`` to overwrite the set."""
        for role in roles:
            await self.add_pending(email, role, staged_by)

    async def replace_pending(self, email: str, roles: List[str], staged_by: str) -> None:
        """Overwrite the full staged-role set for ``email``."""
        await self._pending.delete_many({"email": email.lower()})
        for role in roles:
            await self.add_pending(email, role, staged_by)

    async def delete_pending(self, email: str) -> int:
        res = await self._pending.delete_many({"email": email.lower()})
        return res.deleted_count

    async def get_pending(self, email: str) -> Optional[dict]:
        """Aggregate the rows for one email into ``{email, roles, staged_by, staged_at}``."""
        rows = [
            d async for d in self._pending.find({"email": email.lower()}, projection=_PROJECTION)
        ]
        if not rows:
            return None
        return _aggregate_pending(email.lower(), rows)

    async def list_pending(self, email: Optional[str] = None) -> List[dict]:
        """List staged access, aggregated per email. Optional case-insensitive
        substring filter on email."""
        query: dict = {}
        if email:
            query["email"] = {"$regex": re.escape(email.lower())}
        by_email: dict[str, List[dict]] = {}
        async for d in self._pending.find(query, projection=_PROJECTION):
            by_email.setdefault(d["email"], []).append(d)
        return [_aggregate_pending(em, rows) for em, rows in sorted(by_email.items())]


def _aggregate_pending(email: str, rows: List[dict]) -> dict:
    # staged_by/at reflect the most recent staging action for the email.
    latest = max(rows, key=lambda r: r.get("staged_at") or "")
    return {
        "email": email,
        "roles": sorted(r["role"] for r in rows),
        "staged_by": latest.get("staged_by"),
        "staged_at": latest.get("staged_at"),
    }
