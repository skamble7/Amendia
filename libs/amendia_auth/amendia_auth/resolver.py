# amendia_auth/resolver.py
"""Principal → Amendia user resolution.

The library ships the HTTP resolver used by every enforcing service: it POSTs to
the identity service's internal resolve endpoint (JIT-provisioning happens there)
carrying the shared internal token. The identity service itself injects a *local*
resolver instead, so it never HTTP-calls itself — both satisfy ``PrincipalResolver``.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

import httpx

from .errors import AuthError
from .models import Principal, ResolvedUser

INTERNAL_HEADER = "X-Amendia-Internal"


@runtime_checkable
class PrincipalResolver(Protocol):
    async def resolve(self, principal: Principal) -> ResolvedUser: ...


class HttpIdentityResolver:
    """Calls ``POST {identity_base_url}/internal/resolve-principal``."""

    def __init__(
        self,
        base_url: str,
        internal_token: str,
        *,
        timeout: float = 10.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._internal_token = internal_token
        self._timeout = timeout
        self._client = client  # if provided, reused; else per-call client

    async def resolve(self, principal: Principal) -> ResolvedUser:
        url = f"{self._base_url}/internal/resolve-principal"
        payload = {
            "iss": principal.iss,
            "sub": principal.sub,
            "email": principal.email,
            "name": principal.name,
        }
        headers = {INTERNAL_HEADER: self._internal_token}
        try:
            if self._client is not None:
                resp = await self._client.post(url, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise AuthError(f"identity_unreachable:{exc}")

        if resp.status_code >= 400:
            raise AuthError(f"resolve_failed:{resp.status_code}")
        return ResolvedUser.model_validate(resp.json())
