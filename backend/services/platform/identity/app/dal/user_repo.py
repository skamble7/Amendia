# app/dal/user_repo.py
"""User aggregate repository."""
from __future__ import annotations

import re
import uuid
from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.dal.base import DuplicateError, utcnow_iso
from app.models.identity import User, UserStatus

_PROJECTION = {"_id": 0}


def new_user_id() -> str:
    return "usr-" + uuid.uuid4().hex[:12]


class UserRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._coll = collection

    async def get_by_identity(self, iss: str, sub: str) -> Optional[User]:
        doc = await self._coll.find_one(
            {"identities": {"$elemMatch": {"iss": iss, "sub": sub}}}, projection=_PROJECTION
        )
        return User.model_validate(doc) if doc else None

    async def get(self, amendia_user_id: str) -> Optional[User]:
        doc = await self._coll.find_one({"amendia_user_id": amendia_user_id}, projection=_PROJECTION)
        return User.model_validate(doc) if doc else None

    async def get_by_email(self, email: str) -> Optional[User]:
        """Find a provisioned user by (case-insensitive) email. Used to detect a
        stage-access request for an email that already belongs to a user."""
        doc = await self._coll.find_one(
            {"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}},
            projection=_PROJECTION,
        )
        return User.model_validate(doc) if doc else None

    async def emails_in_use(self, emails: List[str]) -> set[str]:
        """The subset of ``emails`` (compared case-insensitively) that already belong
        to a provisioned user, returned lowercased. Used to keep staged access for a
        now-provisioned email out of the Pending tab and to reconcile stale rows."""
        in_use: set[str] = set()
        for email in {e.lower() for e in emails if e}:
            if await self.get_by_email(email) is not None:
                in_use.add(email)
        return in_use

    async def active_ids_among(self, user_ids: List[str]) -> List[str]:
        """Subset of ``user_ids`` whose accounts are currently active. Used by the
        last-admin guardrail to count live holders of a role."""
        if not user_ids:
            return []
        cursor = self._coll.find(
            {"amendia_user_id": {"$in": user_ids}, "status": UserStatus.ACTIVE.value},
            projection=_PROJECTION,
        )
        return [d["amendia_user_id"] async for d in cursor]

    async def insert(
        self, *, iss: str, sub: str, email: Optional[str], display_name: Optional[str], status: str
    ) -> User:
        now = utcnow_iso()
        doc = {
            "amendia_user_id": new_user_id(),
            "identities": [{"iss": iss, "sub": sub}],
            "email": email,
            "display_name": display_name,
            "status": status,
            "created_at": now,
            "updated_at": now,
        }
        try:
            await self._coll.insert_one(doc)
        except DuplicateKeyError:
            # Concurrent JIT for the same identity — surface for a clean retry.
            raise DuplicateError(f"identity {iss}/{sub}")
        doc.pop("_id", None)
        return User.model_validate(doc)

    async def update_display(
        self, amendia_user_id: str, *, email: Optional[str], display_name: Optional[str]
    ) -> Optional[User]:
        """Update stored email/display_name if either changed (keeps them fresh)."""
        set_fields = {"updated_at": utcnow_iso()}
        if email is not None:
            set_fields["email"] = email
        if display_name is not None:
            set_fields["display_name"] = display_name
        doc = await self._coll.find_one_and_update(
            {"amendia_user_id": amendia_user_id},
            {"$set": set_fields},
            projection=_PROJECTION,
            return_document=ReturnDocument.AFTER,
        )
        return User.model_validate(doc) if doc else None

    async def set_status(self, amendia_user_id: str, status: UserStatus) -> Optional[User]:
        doc = await self._coll.find_one_and_update(
            {"amendia_user_id": amendia_user_id},
            {"$set": {"status": status.value, "updated_at": utcnow_iso()}},
            projection=_PROJECTION,
            return_document=ReturnDocument.AFTER,
        )
        return User.model_validate(doc) if doc else None

    async def list(
        self, *, status: Optional[str] = None, user_ids: Optional[List[str]] = None,
        limit: int = 50, offset: int = 0,
    ) -> List[User]:
        query: dict = {}
        if status:
            query["status"] = status
        if user_ids is not None:
            query["amendia_user_id"] = {"$in": user_ids}
        cursor = self._coll.find(query, projection=_PROJECTION).sort("created_at", 1).skip(offset).limit(limit)
        return [User.model_validate(d) async for d in cursor]
