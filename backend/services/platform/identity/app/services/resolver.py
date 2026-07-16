# app/services/resolver.py
"""Principal → Amendia user resolution with JIT provisioning.

First authenticated request from an unknown ``(iss, sub)`` creates the user
(status from ``IDENTITY_JIT_DEFAULT_STATUS``) and materialises any role
assignments seeded by email. Repeat requests return the same user; a changed
email/name is written back. This is the one place the identity model is mutated
by authentication — it never reads vendor role/group claims.

Also exposes ``LocalResolver`` so the service can satisfy ``amendia_auth``'s
``PrincipalResolver`` for its own ``/me`` and admin guards without HTTP-calling
itself.
"""
from __future__ import annotations

import logging
from typing import Optional

from amendia_auth import Principal, ResolvedUser

from app.dal.role_repo import RoleRepository
from app.dal.user_repo import UserRepository
from app.models.identity import User

logger = logging.getLogger(__name__)


class ResolveService:
    def __init__(
        self, user_repo: UserRepository, role_repo: RoleRepository, *, jit_default_status: str = "active"
    ) -> None:
        self._users = user_repo
        self._roles = role_repo
        self._jit_status = jit_default_status

    async def resolve(
        self, *, iss: str, sub: str, email: Optional[str] = None, name: Optional[str] = None
    ) -> ResolvedUser:
        user = await self._users.get_by_identity(iss, sub)
        if user is None:
            user = await self._provision(iss=iss, sub=sub, email=email, name=name)
        else:
            user = await self._reconcile(user, email=email, name=name)

        roles = await self._roles.roles_for(user.amendia_user_id)
        return ResolvedUser(
            amendia_user_id=user.amendia_user_id,
            email=user.email,
            display_name=user.display_name,
            status=user.status.value if hasattr(user.status, "value") else str(user.status),
            roles=roles,
        )

    async def _provision(self, *, iss: str, sub: str, email, name) -> User:
        from app.dal.base import DuplicateError

        try:
            user = await self._users.insert(
                iss=iss, sub=sub, email=email, display_name=name, status=self._jit_status
            )
        except DuplicateError:
            # Lost a JIT race for this identity — the other writer created it.
            existing = await self._users.get_by_identity(iss, sub)
            if existing is None:  # pragma: no cover - defensive
                raise
            return existing

        logger.info("JIT-provisioned user %s for %s/%s (status=%s)",
                    user.amendia_user_id, iss, sub, self._jit_status)
        await self._materialise_pending_roles(user)
        return user

    async def _reconcile(self, user: User, *, email, name) -> User:
        stale_email = email is not None and email != user.email
        stale_name = name is not None and name != user.display_name
        if stale_email or stale_name:
            updated = await self._users.update_display(
                user.amendia_user_id, email=email, display_name=name
            )
            if updated is not None:
                return updated
        return user

    async def _materialise_pending_roles(self, user: User) -> None:
        """Attach any email-staged roles to the freshly-provisioned user, then delete
        the staged rows. Removal enforces the invariant that a pending row exists only
        for an email that has *not* signed in yet — so the Pending tab never lists a
        provisioned user. Idempotent: re-running finds nothing to do."""
        pending = await self._roles.pending_grants_for_email(user.email)
        if not pending:
            return
        for grant in pending:
            # Attribute the grant to whoever staged it (the admin, or "seed"), not a
            # generic marker — the user-detail audit line ("assigned by") stays honest.
            if await self._roles.assign_if_absent(user.amendia_user_id, grant["role"], grant["staged_by"]):
                logger.info("attached staged role %s to %s (%s)", grant["role"], user.amendia_user_id, user.email)
        await self._roles.delete_pending(user.email)


class LocalResolver:
    """Adapts ``ResolveService`` to ``amendia_auth.PrincipalResolver`` so the
    identity service resolves in-process instead of HTTP-calling itself."""

    def __init__(self, service: ResolveService) -> None:
        self._service = service

    async def resolve(self, principal: Principal) -> ResolvedUser:
        return await self._service.resolve(
            iss=principal.iss, sub=principal.sub, email=principal.email, name=principal.name
        )
