# app/services/guardrails.py
"""Admin self-protection + last-admin protection for destructive role/account ops.

Two invariants the platform-admin surface must uphold server-side (the UI renders
them as disabled controls, but the server is the source of truth):

- **self_protection** — an admin may not disable their own account nor revoke their
  own ``role.platform.admin``. Refused with 409 ``self_protection``.
- **last_admin** — the platform must always retain at least one *active* holder of
  ``role.platform.admin``. Revoking/disabling the last one is refused with 409
  ``last_admin``. The count is of active users holding the role, re-checked at
  operation time (after the tentative mutation) so two concurrent admins can't each
  pass a stale pre-check and leave zero admins between them.
"""
from __future__ import annotations

from fastapi import HTTPException

from app.dal.role_repo import RoleRepository
from app.dal.user_repo import UserRepository

ADMIN_ROLE = "role.platform.admin"


def self_protection_error(what: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"error": "self_protection", "message": what},
    )


def last_admin_error(what: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"error": "last_admin", "message": what},
    )


async def active_admin_count(role_repo: RoleRepository, user_repo: UserRepository) -> int:
    """Number of *active* users currently holding ``role.platform.admin``."""
    holders = await role_repo.holders_of(ADMIN_ROLE)
    active = await user_repo.active_ids_among(holders)
    return len(active)
