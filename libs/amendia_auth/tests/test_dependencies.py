# tests/test_dependencies.py
"""FastAPI dependency behaviour with a faked resolver: 401/403 shapes, the
resolve-cache TTL, disabled-user 403, require_roles, principal_or_internal,
and the auth-disabled synthetic user."""
from __future__ import annotations

import time

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from amendia_auth.context import AuthContext
from amendia_auth.dependencies import (
    current_principal,
    current_user,
    principal_or_internal,
    require_internal,
    require_roles,
)
from amendia_auth.models import AuthenticatedUser, Principal, ResolvedUser
from amendia_auth.resolver import INTERNAL_HEADER
from amendia_auth.settings import AuthSettings

from .conftest import AUDIENCE, ISSUER, Idp


class FakeResolver:
    def __init__(self):
        self.calls = 0
        self.status = "active"
        self.roles = ["role.payments.ops_analyst"]

    async def resolve(self, principal: Principal) -> ResolvedUser:
        self.calls += 1
        return ResolvedUser(
            amendia_user_id="usr-riya",
            email=principal.email,
            display_name=principal.name,
            status=self.status,
            roles=self.roles,
        )


def build_app(settings: AuthSettings, idp: Idp, resolver: FakeResolver) -> FastAPI:
    from amendia_auth.validator import TokenValidator

    app = FastAPI()
    validator = TokenValidator(settings, http_client_factory=idp.client_factory())
    app.state.auth = AuthContext(settings, resolver=resolver, validator=validator)

    @app.get("/read")
    async def read(principal=Depends(current_principal)):
        return {"anon": principal is None, "sub": getattr(principal, "sub", None)}

    @app.get("/me")
    async def me(user=Depends(current_user)):
        if user is None:
            return {"anon": True}
        return {"user_id": user.amendia_user_id, "roles": sorted(user.roles)}

    @app.get("/analyst")
    async def analyst(user: AuthenticatedUser = Depends(require_roles("role.payments.ops_analyst"))):
        return {"ok": True, "user_id": user.amendia_user_id}

    @app.get("/approver")
    async def approver(user: AuthenticatedUser = Depends(require_roles("role.payments.ops_approver"))):
        return {"ok": True}

    @app.get("/s2s")
    async def s2s(p=Depends(principal_or_internal)):
        return {"iss": getattr(p, "iss", None)}

    @app.get("/internal-only", dependencies=[Depends(require_internal)])
    async def internal_only():
        return {"ok": True}

    return app


@pytest.fixture
def resolver() -> FakeResolver:
    return FakeResolver()


def _settings(**over) -> AuthSettings:
    base = dict(issuer=ISSUER, audience=AUDIENCE, internal_token="internal-secret", leeway_seconds=10)
    base.update(over)
    return AuthSettings(**base)


async def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_missing_token_401(idp, resolver):
    app = build_app(_settings(), idp, resolver)
    async with await _client(app) as ac:
        r = await ac.get("/read")
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "invalid_token"
    assert r.headers["WWW-Authenticate"].startswith("Bearer")


async def test_valid_token_read_ok(idp, resolver):
    app = build_app(_settings(), idp, resolver)
    token = idp.mint("k1", sub="kc-1")
    async with await _client(app) as ac:
        r = await ac.get("/read", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {"anon": False, "sub": "kc-1"}


async def test_current_user_resolves_roles(idp, resolver):
    app = build_app(_settings(), idp, resolver)
    token = idp.mint("k1")
    async with await _client(app) as ac:
        r = await ac.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["user_id"] == "usr-riya"
    assert r.json()["roles"] == ["role.payments.ops_analyst"]


async def test_resolve_cache_ttl_honored(idp, resolver):
    app = build_app(_settings(resolve_cache_ttl_seconds=100), idp, resolver)
    token = idp.mint("k1")
    async with await _client(app) as ac:
        await ac.get("/me", headers={"Authorization": f"Bearer {token}"})
        await ac.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resolver.calls == 1  # second request served from cache


async def test_disabled_user_403(idp, resolver):
    resolver.status = "disabled"
    app = build_app(_settings(), idp, resolver)
    token = idp.mint("k1")
    async with await _client(app) as ac:
        r = await ac.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "user_disabled"


async def test_require_roles_allows_and_forbids(idp, resolver):
    app = build_app(_settings(), idp, resolver)
    token = idp.mint("k1")
    async with await _client(app) as ac:
        ok = await ac.get("/analyst", headers={"Authorization": f"Bearer {token}"})
        forbidden = await ac.get("/approver", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["missing_role"] == "role.payments.ops_approver"


async def test_principal_or_internal_accepts_internal_token(idp, resolver):
    app = build_app(_settings(), idp, resolver)
    async with await _client(app) as ac:
        r = await ac.get("/s2s", headers={INTERNAL_HEADER: "internal-secret"})
    assert r.status_code == 200
    assert r.json()["iss"] == "amendia:internal"


async def test_principal_or_internal_rejects_bad_internal_token(idp, resolver):
    app = build_app(_settings(), idp, resolver)
    async with await _client(app) as ac:
        r = await ac.get("/s2s", headers={INTERNAL_HEADER: "wrong"})
    assert r.status_code == 401


async def test_require_internal_guard(idp, resolver):
    app = build_app(_settings(), idp, resolver)
    async with await _client(app) as ac:
        ok = await ac.get("/internal-only", headers={INTERNAL_HEADER: "internal-secret"})
        bad = await ac.get("/internal-only")
    assert ok.status_code == 200
    assert bad.status_code == 401


async def test_auth_disabled_yields_synthetic_user(idp, resolver):
    app = build_app(_settings(auth_disabled=True), idp, resolver)
    async with await _client(app) as ac:
        r = await ac.get("/me")  # no token at all
    assert r.status_code == 200
    assert r.json()["user_id"] == "usr-dev"
    assert "role.platform.admin" in r.json()["roles"]
