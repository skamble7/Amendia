# amendia_auth/context.py
"""Per-app auth runtime: the validator, the resolver, and a short-TTL cache.

A service builds one ``AuthContext`` in its lifespan and stores it on
``app.state.auth``; the FastAPI dependencies read it from there. The resolve
cache (keyed by ``(iss, sub)``) keeps per-request role lookups off the identity
service while still letting role changes propagate within the TTL.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

from .models import AuthenticatedUser, Principal, ResolvedUser
from .resolver import HttpIdentityResolver, PrincipalResolver
from .settings import AuthSettings
from .validator import TokenValidator

logger = logging.getLogger(__name__)

# Sentinel identity for authenticated service-to-service calls (internal token).
INTERNAL_PRINCIPAL = Principal(iss="amendia:internal", sub="internal-service")


class AuthContext:
    def __init__(
        self,
        settings: AuthSettings,
        *,
        resolver: Optional[PrincipalResolver] = None,
        validator: Optional[TokenValidator] = None,
    ) -> None:
        self.settings = settings
        self.validator = validator or TokenValidator(settings)
        self.resolver: PrincipalResolver = resolver or HttpIdentityResolver(
            settings.identity_base_url, settings.internal_token
        )
        self._cache: Dict[Tuple[str, str], Tuple[float, ResolvedUser]] = {}
        if settings.auth_disabled:
            logger.warning(
                "AUTH DISABLED — every request is served as synthetic user %s with roles %s. "
                "This must never be set in a real deployment.",
                settings.dev_user_id,
                sorted(settings.synthetic_roles),
            )

    async def resolve_cached(self, principal: Principal) -> ResolvedUser:
        key = (principal.iss, principal.sub)
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
        resolved = await self.resolver.resolve(principal)
        self._cache[key] = (now + self.settings.resolve_cache_ttl_seconds, resolved)
        return resolved

    def invalidate_cache(self) -> None:
        self._cache.clear()

    def synthetic_user(self) -> AuthenticatedUser:
        principal = Principal(
            iss="amendia:auth-disabled",
            sub=self.settings.dev_user_id,
            email=self.settings.dev_user_email,
            name=self.settings.dev_user_name,
        )
        return AuthenticatedUser(
            amendia_user_id=self.settings.dev_user_id,
            email=self.settings.dev_user_email,
            display_name=self.settings.dev_user_name,
            roles=set(self.settings.synthetic_roles),
            principal=principal,
        )
