# app/routers/pending.py
"""Pending (staged) role-assignment administration — all guarded by
``role.platform.admin``.

Staged access lets an admin grant roles to someone *before* they first sign in:
rows are keyed by email and materialised onto the user at JIT-provision time
(``ResolveService._materialise_pending_roles``) — that attach behaviour is
unchanged here. A stage request for an email that already belongs to a provisioned
user is refused (409 ``user_exists``) and points the caller at that user's id so the
UI can redirect to their detail page instead.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from amendia_auth import AuthenticatedUser, require_roles

from app.dal.role_repo import RoleRepository
from app.dal.user_repo import UserRepository
from app.deps import get_role_repo, get_user_repo
from app.models.identity import PendingView, ReplacePendingRequest, StagePendingRequest

router = APIRouter(prefix="/pending-role-assignments", tags=["admin"])

_ADMIN = require_roles("role.platform.admin")


@router.get("", response_model=List[PendingView])
async def list_pending(
    email: Optional[str] = Query(None, description="case-insensitive substring filter"),
    _: AuthenticatedUser = Depends(_ADMIN),
    role_repo: RoleRepository = Depends(get_role_repo),
):
    return await role_repo.list_pending(email)


@router.post("", response_model=PendingView, status_code=201)
async def stage_pending(
    body: StagePendingRequest,
    admin: AuthenticatedUser = Depends(_ADMIN),
    user_repo: UserRepository = Depends(get_user_repo),
    role_repo: RoleRepository = Depends(get_role_repo),
):
    existing = await user_repo.get_by_email(body.email)
    if existing is not None:
        # The email already belongs to a real user — staging is meaningless; send the
        # UI to that user's detail so roles are assigned there instead.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "user_exists",
                "amendia_user_id": existing.amendia_user_id,
                "email": body.email.lower(),
                "message": "This email already belongs to a provisioned user.",
            },
        )
    await role_repo.stage_pending(body.email, body.roles, admin.amendia_user_id)
    staged = await role_repo.get_pending(body.email)
    return staged


@router.put("/{email}", response_model=PendingView)
async def replace_pending(
    email: str,
    body: ReplacePendingRequest,
    admin: AuthenticatedUser = Depends(_ADMIN),
    role_repo: RoleRepository = Depends(get_role_repo),
):
    await role_repo.replace_pending(email, body.roles, admin.amendia_user_id)
    return await role_repo.get_pending(email)


@router.delete("/{email}", status_code=204)
async def delete_pending(
    email: str,
    _: AuthenticatedUser = Depends(_ADMIN),
    role_repo: RoleRepository = Depends(get_role_repo),
):
    removed = await role_repo.delete_pending(email)
    if removed == 0:
        raise HTTPException(status_code=404, detail=f"no staged access for '{email}'")
    return Response(status_code=204)
