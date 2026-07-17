# app/routers/pending.py
"""Pending (staged) role-assignment administration — all guarded by
``role.platform.admin``.

Staged access lets an admin grant roles to someone *before* they first sign in:
rows are keyed by email and materialised onto the user at JIT-provision time
(``ResolveService._materialise_pending_roles``, which also *removes* them). The tab
therefore holds a single invariant — **a pending row exists only for an email that has
not signed in yet** — enforced at every write path:

- ``POST`` / ``PUT`` refuse an email that already belongs to a provisioned user
  (409 ``user_exists``, pointing the caller at that user's detail page instead);
- first login materialises then deletes the rows;
- ``GET`` additionally filters out any email now provisioned (defence in depth), and a
  startup reconcile purges legacy strays.
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


def _user_exists_conflict(user_id: str, email: str) -> HTTPException:
    # Staging for an already-provisioned email is meaningless; send the UI to that
    # user's detail so roles are assigned there instead.
    return HTTPException(
        status_code=409,
        detail={
            "error": "user_exists",
            "amendia_user_id": user_id,
            "email": email.lower(),
            "message": "This email already belongs to a provisioned user.",
        },
    )


@router.get("", response_model=List[PendingView])
async def list_pending(
    email: Optional[str] = Query(None, description="case-insensitive substring filter"),
    _: AuthenticatedUser = Depends(_ADMIN),
    role_repo: RoleRepository = Depends(get_role_repo),
    user_repo: UserRepository = Depends(get_user_repo),
):
    staged = await role_repo.list_pending(email)
    if not staged:
        return staged
    # Defence in depth: never surface staged access for an email that has since been
    # provisioned (its roles are already live on the user).
    in_use = await user_repo.emails_in_use([s["email"] for s in staged])
    return [s for s in staged if s["email"].lower() not in in_use]


@router.post("", response_model=PendingView, status_code=201)
async def stage_pending(
    body: StagePendingRequest,
    admin: AuthenticatedUser = Depends(_ADMIN),
    user_repo: UserRepository = Depends(get_user_repo),
    role_repo: RoleRepository = Depends(get_role_repo),
):
    existing = await user_repo.get_by_email(body.email)
    if existing is not None:
        raise _user_exists_conflict(existing.amendia_user_id, body.email)
    await role_repo.stage_pending(body.email, body.roles, admin.amendia_user_id)
    staged = await role_repo.get_pending(body.email)
    return staged


@router.put("/{email}", response_model=PendingView)
async def replace_pending(
    email: str,
    body: ReplacePendingRequest,
    admin: AuthenticatedUser = Depends(_ADMIN),
    user_repo: UserRepository = Depends(get_user_repo),
    role_repo: RoleRepository = Depends(get_role_repo),
):
    existing = await user_repo.get_by_email(email)
    if existing is not None:
        raise _user_exists_conflict(existing.amendia_user_id, email)
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
