# amendia_auth
"""Amendia shared authentication/authorization library.

Governing principle: authenticate with the IdP, authorize in Amendia. Only
``iss`` + ``sub`` (plus email/name for display) are trusted from tokens; roles
come from the identity service. See ``backend/docs/amendia_auth_architecture.md``.
"""
from __future__ import annotations

from .context import INTERNAL_PRINCIPAL, AuthContext
from .dependencies import (
    current_principal,
    current_user,
    get_auth,
    principal_or_internal,
    require_internal,
    require_roles,
)
from .errors import AuthError
from .models import AuthenticatedUser, Principal, ResolvedUser
from .resolver import (
    INTERNAL_HEADER,
    HttpIdentityResolver,
    PrincipalResolver,
)
from .settings import AuthSettings, load_auth_settings
from .validator import TokenValidator

__all__ = [
    "AuthContext",
    "AuthError",
    "AuthSettings",
    "AuthenticatedUser",
    "HttpIdentityResolver",
    "INTERNAL_HEADER",
    "INTERNAL_PRINCIPAL",
    "Principal",
    "PrincipalResolver",
    "ResolvedUser",
    "TokenValidator",
    "current_principal",
    "current_user",
    "get_auth",
    "load_auth_settings",
    "principal_or_internal",
    "require_internal",
    "require_roles",
]
