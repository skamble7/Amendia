# amendia_auth/validator.py
"""OIDC bearer-token validation as a standard resource server.

Discovery (``{issuer}/.well-known/openid-configuration``) → ``jwks_uri`` → keys,
cached in-process with a TTL and refreshed once on an unknown ``kid`` (rotation
tolerance). Verifies signature (RS/ES family only — ``alg:none`` and HS* are
rejected to avoid algorithm-confusion), exact ``iss``, ``aud`` contains the
configured audience, and ``exp``/``nbf`` with small leeway. Returns a
``Principal`` or raises ``AuthError``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Dict, Optional

import httpx
import jwt

from .errors import AuthError
from .models import Principal
from .settings import AuthSettings

logger = logging.getLogger(__name__)

# Asymmetric families only. HS* (symmetric) and "none" are refused so a token
# signed with a public key or unsigned can never be confused for a valid one.
ALLOWED_ALGS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]

# Type of a zero-arg factory yielding an httpx.AsyncClient context manager.
HttpClientFactory = Callable[[], httpx.AsyncClient]


class TokenValidator:
    def __init__(
        self,
        settings: AuthSettings,
        *,
        http_client_factory: Optional[HttpClientFactory] = None,
    ) -> None:
        self._s = settings
        self._client_factory = http_client_factory or (lambda: httpx.AsyncClient(timeout=10.0))
        self._jwks_uri: Optional[str] = None
        self._keys: Dict[str, "jwt.PyJWK"] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def validate(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise AuthError(f"malformed_token:{exc}")

        alg = header.get("alg")
        if alg not in ALLOWED_ALGS:
            raise AuthError(f"unsupported_alg:{alg}")

        kid = header.get("kid")
        signing_key = await self._signing_key(kid)

        try:
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=ALLOWED_ALGS,
                audience=self._s.audience,
                issuer=self._s.issuer,
                leeway=self._s.leeway_seconds,
                options={"require": ["exp", "iss", "sub"], "verify_aud": True},
            )
        except jwt.ExpiredSignatureError:
            raise AuthError("expired")
        except jwt.InvalidAudienceError:
            raise AuthError("wrong_audience")
        except jwt.InvalidIssuerError:
            raise AuthError("wrong_issuer")
        except jwt.InvalidTokenError as exc:
            raise AuthError(f"invalid_token:{exc}")

        return Principal(
            iss=claims["iss"],
            sub=claims["sub"],
            email=claims.get("email"),
            name=claims.get("name") or claims.get("preferred_username"),
            raw_claims=claims,
        )

    # ------------------------------------------------------------------ #
    async def _signing_key(self, kid: Optional[str]) -> "jwt.PyJWK":
        # Fresh cache + known kid → use it. Fresh cache + unknown kid → the key
        # may have just rotated, so refresh once. Stale cache → refresh.
        if not self._expired() and kid in self._keys:
            return self._keys[kid]
        await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise AuthError("unknown_kid")
        return key

    def _expired(self) -> bool:
        if not self._keys:
            return True
        return (time.monotonic() - self._fetched_at) >= self._s.jwks_ttl_seconds

    async def _refresh(self) -> None:
        async with self._lock:
            try:
                async with self._client_factory() as client:
                    if self._jwks_uri is None:
                        if self._s.jwks_uri:
                            # Explicit internal JWKS URL — skip discovery (compose).
                            self._jwks_uri = self._s.jwks_uri
                        else:
                            disc_url = f"{self._s.issuer.rstrip('/')}/.well-known/openid-configuration"
                            disc = (await client.get(disc_url)).raise_for_status().json()
                            self._jwks_uri = disc["jwks_uri"]
                    raw = (await client.get(self._jwks_uri)).raise_for_status().json()
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                raise AuthError(f"jwks_unavailable:{exc}")

            jwkset = jwt.PyJWKSet.from_dict(raw)
            self._keys = {k.key_id: k for k in jwkset.keys}
            self._fetched_at = time.monotonic()
            logger.debug("refreshed JWKS: %d key(s)", len(self._keys))
