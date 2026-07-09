# app/routers/admin.py
"""User/role administration — all guarded by ``role.platform.admin``.

The platform-admin persona lists users and assigns/revokes the ``role.*``
vocabulary; changes take effect within the resolver cache TTL of the enforcing
services. Audit is limited to ``assigned_by/at`` this iteration (design doc §5).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from amendia_auth import AuthenticatedUser, require_roles

from app.dal.base import DuplicateError
from app.dal.role_repo import RoleRepository
from app.dal.user_repo import UserRepository
from app.deps import get_role_repo, get_user_repo
from app.models.identity import AssignRoleRequest, User, UserStatus, UserView
from app.services.guardrails import (
    ADMIN_ROLE,
    active_admin_count,
    last_admin_error,
    self_protection_error,
)

router = APIRouter(prefix="/users", tags=["admin"])

_ADMIN = require_roles("role.platform.admin")


async def _to_view(user: User, role_repo: RoleRepository) -> UserView:
    details = await role_repo.assignments_for(user.amendia_user_id)
    return UserView(
        amendia_user_id=user.amendia_user_id,
        identities=user.identities,
        email=user.email,
        display_name=user.display_name,
        status=user.status.value,
        roles=[d["role"] for d in details],
        role_details=details,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.get("", response_model=List[UserView])
async def list_users(
    status: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: AuthenticatedUser = Depends(_ADMIN),
    user_repo: UserRepository = Depends(get_user_repo),
    role_repo: RoleRepository = Depends(get_role_repo),
):
    user_ids = await role_repo.user_ids_with_role(role) if role else None
    if role is not None and not user_ids:
        return []
    users = await user_repo.list(status=status, user_ids=user_ids, limit=limit, offset=offset)
    return [await _to_view(u, role_repo) for u in users]


@router.get("/{amendia_user_id}", response_model=UserView)
async def get_user(
    amendia_user_id: str,
    _: AuthenticatedUser = Depends(_ADMIN),
    user_repo: UserRepository = Depends(get_user_repo),
    role_repo: RoleRepository = Depends(get_role_repo),
):
    user = await user_repo.get(amendia_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"Unknown user: {amendia_user_id}")
    return await _to_view(user, role_repo)


@router.post("/{amendia_user_id}/roles", response_model=UserView, status_code=201)
async def assign_role(
    amendia_user_id: str,
    body: AssignRoleRequest,
    admin: AuthenticatedUser = Depends(_ADMIN),
    user_repo: UserRepository = Depends(get_user_repo),
    role_repo: RoleRepository = Depends(get_role_repo),
):
    user = await user_repo.get(amendia_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"Unknown user: {amendia_user_id}")
    try:
        await role_repo.assign(amendia_user_id, body.role, admin.amendia_user_id)
    except DuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return await _to_view(user, role_repo)


@router.delete("/{amendia_user_id}/roles/{role}", response_model=UserView)
async def revoke_role(
    amendia_user_id: str,
    role: str,
    admin: AuthenticatedUser = Depends(_ADMIN),
    user_repo: UserRepository = Depends(get_user_repo),
    role_repo: RoleRepository = Depends(get_role_repo),
):
    user = await user_repo.get(amendia_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"Unknown user: {amendia_user_id}")

    # Self-protection: an admin can't strip their own admin role (checked before any
    # mutation, and independent of how many other admins exist).
    if role == ADMIN_ROLE and amendia_user_id == admin.amendia_user_id:
        raise self_protection_error("You cannot revoke your own platform-admin role.")

    removed = await role_repo.pop_assignment(amendia_user_id, role)
    if removed is None:
        raise HTTPException(status_code=404, detail=f"user has no role '{role}'")

    # Last-admin protection, race-tolerant: the tentative delete is already applied,
    # so re-counting active admins now reflects the post-revoke world. If none remain,
    # restore the assignment and refuse. Concurrent revokers each restore, so at least
    # one admin always survives.
    if role == ADMIN_ROLE and await active_admin_count(role_repo, user_repo) == 0:
        await role_repo.restore_assignment(removed)
        raise last_admin_error("Refused: this is the last active platform admin.")

    return await _to_view(user, role_repo)


@router.post("/{amendia_user_id}/disable", response_model=UserView)
async def disable_user(
    amendia_user_id: str,
    admin: AuthenticatedUser = Depends(_ADMIN),
    user_repo: UserRepository = Depends(get_user_repo),
    role_repo: RoleRepository = Depends(get_role_repo),
):
    # Self-protection: an admin can't lock themselves out.
    if amendia_user_id == admin.amendia_user_id:
        raise self_protection_error("You cannot disable your own account.")

    existing = await user_repo.get(amendia_user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Unknown user: {amendia_user_id}")

    user = await user_repo.set_status(amendia_user_id, UserStatus.DISABLED)
    if user is None:  # pragma: no cover - just fetched above
        raise HTTPException(status_code=404, detail=f"Unknown user: {amendia_user_id}")

    # Last-admin protection, race-tolerant: disabling drops the user from the active
    # count, so re-check afterwards and roll the status back if it emptied the admins.
    is_admin = ADMIN_ROLE in await role_repo.roles_for(amendia_user_id)
    if is_admin and await active_admin_count(role_repo, user_repo) == 0:
        user = await user_repo.set_status(amendia_user_id, UserStatus.ACTIVE)
        raise last_admin_error("Refused: this is the last active platform admin.")

    return await _to_view(user, role_repo)


@router.post("/{amendia_user_id}/enable", response_model=UserView)
async def enable_user(
    amendia_user_id: str,
    _: AuthenticatedUser = Depends(_ADMIN),
    user_repo: UserRepository = Depends(get_user_repo),
    role_repo: RoleRepository = Depends(get_role_repo),
):
    user = await user_repo.set_status(amendia_user_id, UserStatus.ACTIVE)
    if user is None:
        raise HTTPException(status_code=404, detail=f"Unknown user: {amendia_user_id}")
    return await _to_view(user, role_repo)
