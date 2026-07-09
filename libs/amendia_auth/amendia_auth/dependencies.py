# amendia_auth/dependencies.py
"""FastAPI dependencies built on an ``AuthContext`` at ``request.app.state.auth``.

- ``current_principal`` — validate the bearer → ``Principal`` (401 on failure).
- ``current_user`` — resolve the principal → ``AuthenticatedUser`` (403 if disabled).
- ``require_roles(*roles)`` — role guard on top of ``current_user`` (403 names the
  missing role).
- ``principal_or_internal`` — accept either a user bearer or the shared internal
  token, for endpoints reachable service-to-service inside the deployment boundary.
- ``require_internal`` — guard for internal-only endpoints (identity's resolve).

Auth-disabled mode yields a synthetic user everywhere. Compat-stub mode lets
principal-only endpoints through with no token (returns ``None``) — see Part E.
None of these ever echo the token; failures carry ``error="invalid_token"``.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .context import INTERNAL_PRINCIPAL, AuthContext
from .errors import AuthError
from .models import AuthenticatedUser, Principal
from .resolver import INTERNAL_HEADER

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(reason: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"error": "invalid_token", "reason": reason},
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )


def get_auth(request: Request) -> AuthContext:
    auth = getattr(request.app.state, "auth", None)
    if auth is None:  # pragma: no cover - misconfiguration
        raise HTTPException(status_code=500, detail="auth context not configured")
    return auth


async def _validate_or_401(
    creds: Optional[HTTPAuthorizationCredentials], auth: AuthContext
) -> Optional[Principal]:
    """Validate a bearer if present; None if absent. Raises 401 on a bad token."""
    if creds is None or not creds.credentials:
        return None
    try:
        return await auth.validator.validate(creds.credentials)
    except AuthError as exc:
        raise _unauthorized(exc.reason)


async def current_principal(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    auth: AuthContext = Depends(get_auth),
) -> Principal:
    if auth.settings.auth_disabled:
        return auth.synthetic_user().principal
    principal = await _validate_or_401(creds, auth)
    if principal is None:
        raise _unauthorized("missing_token")
    return principal


async def current_user(
    principal: Principal = Depends(current_principal),
    auth: AuthContext = Depends(get_auth),
) -> AuthenticatedUser:
    if auth.settings.auth_disabled:
        return auth.synthetic_user()
    resolved = await auth.resolve_cached(principal)
    if resolved.status == "disabled":
        raise HTTPException(status_code=403, detail={"error": "user_disabled"})
    return AuthenticatedUser(
        amendia_user_id=resolved.amendia_user_id,
        email=resolved.email,
        display_name=resolved.display_name,
        roles=set(resolved.roles),
        principal=principal,
    )


def require_roles(*roles: str):
    """Dependency factory: 403 (naming the missing role) unless the caller holds
    every listed role."""

    async def _dep(user: AuthenticatedUser = Depends(current_user)) -> AuthenticatedUser:
        missing = next((r for r in roles if r not in user.roles), None)
        if missing is not None:
            raise HTTPException(
                status_code=403,
                detail={"error": "forbidden", "missing_role": missing},
            )
        return user

    return _dep


async def principal_or_internal(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    auth: AuthContext = Depends(get_auth),
) -> Optional[Principal]:
    """Accept a user bearer OR the shared internal token (service-to-service)."""
    token = request.headers.get(INTERNAL_HEADER)
    if token and auth.settings.internal_token and token == auth.settings.internal_token:
        return INTERNAL_PRINCIPAL
    return await current_principal(creds, auth)


async def require_internal(
    request: Request, auth: AuthContext = Depends(get_auth)
) -> None:
    """Guard for internal-only endpoints (e.g. identity resolve). Rejects unless
    the shared internal token matches."""
    if auth.settings.auth_disabled:
        return
    token = request.headers.get(INTERNAL_HEADER)
    if not token or not auth.settings.internal_token or token != auth.settings.internal_token:
        raise HTTPException(status_code=401, detail={"error": "invalid_internal_token"})
