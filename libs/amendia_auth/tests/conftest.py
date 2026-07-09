# tests/conftest.py
"""Auth-lib fixtures: locally-generated RSA keypairs, a JWKS served over an
httpx MockTransport (no network), a token minter, and a validator wired to it."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from amendia_auth.settings import AuthSettings
from amendia_auth.validator import TokenValidator

ISSUER = "https://idp.test/realms/amendia-dev"
AUDIENCE = "amendia-api"


def _make_key(kid: str):
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(priv.public_key()))
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return priv, jwk


@dataclass
class Idp:
    """A fake IdP: one or more RSA keys, discovery + JWKS over MockTransport."""

    issuer: str = ISSUER
    jwks_uri: str = f"{ISSUER}/protocol/openid-connect/certs"
    _privs: Dict[str, object] = field(default_factory=dict)
    _jwks: List[dict] = field(default_factory=list)
    discovery_calls: int = 0
    jwks_calls: int = 0

    def add_key(self, kid: str) -> None:
        priv, jwk = _make_key(kid)
        self._privs[kid] = priv
        self._jwks.append(jwk)

    def drop_keys(self) -> None:
        self._privs.clear()
        self._jwks.clear()

    def mint(
        self,
        kid: str,
        *,
        sub: str = "kc-sub-riya",
        iss: Optional[str] = None,
        aud=AUDIENCE,
        email: Optional[str] = "riya@bank.test",
        name: Optional[str] = "Riya",
        exp_delta: int = 300,
        nbf_delta: int = -10,
        alg: str = "RS256",
        extra: Optional[dict] = None,
    ) -> str:
        now = int(time.time())
        claims = {
            "iss": iss or self.issuer,
            "sub": sub,
            "aud": aud,
            "iat": now,
            "nbf": now + nbf_delta,
            "exp": now + exp_delta,
        }
        if email is not None:
            claims["email"] = email
        if name is not None:
            claims["name"] = name
        if extra:
            claims.update(extra)
        return jwt.encode(claims, self._privs[kid], algorithm=alg, headers={"kid": kid})

    def client_factory(self):
        def _handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.endswith("/.well-known/openid-configuration"):
                self.discovery_calls += 1
                return httpx.Response(200, json={"issuer": self.issuer, "jwks_uri": self.jwks_uri})
            if url == self.jwks_uri:
                self.jwks_calls += 1
                return httpx.Response(200, json={"keys": self._jwks})
            return httpx.Response(404)

        transport = httpx.MockTransport(_handler)
        return lambda: httpx.AsyncClient(transport=transport, timeout=5.0)


@pytest.fixture
def idp() -> Idp:
    idp = Idp()
    idp.add_key("k1")
    return idp


@pytest.fixture
def auth_settings() -> AuthSettings:
    return AuthSettings(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_ttl_seconds=600,
        leeway_seconds=10,
        internal_token="internal-secret",
    )


@pytest.fixture
def validator(idp: Idp, auth_settings: AuthSettings) -> TokenValidator:
    return TokenValidator(auth_settings, http_client_factory=idp.client_factory())
