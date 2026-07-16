# app/routers/roles.py
"""Roles-in-use catalog — the assignable-role source for the admin UI.

Read-only; baseline-guarded (``principal_or_internal`` at the app level). Any authenticated
principal may read it — a platform admin needs it to grant pack-local roles, and it exposes no
mutation. Role ids are derived from active packs' bindings; see ``app.services.roles``.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends

from app.dal.pack_repo import ProcessPackRepository
from app.deps import get_pack_repo
from app.models.registry import RoleInUse
from app.services.roles import list_roles_in_use

router = APIRouter(tags=["roles"])


@router.get("/roles", response_model=List[RoleInUse])
async def list_roles(pack_repo: ProcessPackRepository = Depends(get_pack_repo)):
    return await list_roles_in_use(pack_repo)
