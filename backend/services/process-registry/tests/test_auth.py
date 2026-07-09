# tests/test_auth.py
"""Targeted enforcement tests (strict auth): 401 unauthenticated, the internal-token
service-to-service path, and 403 wrong-role on a representative mutation."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from amendia_auth import (
    AuthContext,
    AuthenticatedUser,
    Principal,
    current_user,
    principal_or_internal,
)
from amendia_auth.resolver import INTERNAL_HEADER
from amendia_auth.settings import AuthSettings

from app.db.mongo import CAPABILITIES
from app.dal.capability_repo import CapabilityRepository
from app.deps import get_capability_repo, get_pack_repo
from app.main import create_app

INTERNAL = "test-internal"


class Holder:
    def __init__(self):
        self.user = None


def user_without_owner():
    return AuthenticatedUser(
        amendia_user_id="usr-riya",
        roles={"role.payments.ops_analyst"},
        principal=Principal(iss="t", sub="riya"),
    )


@pytest_asyncio.fixture
async def strict_client(db, cap_repo, pack_repo):
    holder = Holder()
    app = create_app()
    # Strict: no compat, not disabled. Real 401/403 paths exercised.
    app.state.auth = AuthContext(AuthSettings(issuer="t", internal_token=INTERNAL))
    app.dependency_overrides[get_capability_repo] = lambda: cap_repo
    app.dependency_overrides[get_pack_repo] = lambda: pack_repo
    # current_user is what require_roles resolves through; override to a chosen user.
    app.dependency_overrides[current_user] = lambda: holder.user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, holder
    app.dependency_overrides.clear()


async def test_unauthenticated_read_401(strict_client):
    ac, _ = strict_client
    r = await ac.get("/capabilities")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Bearer")


async def test_internal_token_read_ok(strict_client):
    ac, _ = strict_client
    r = await ac.get("/capabilities", headers={INTERNAL_HEADER: INTERNAL})
    assert r.status_code == 200


async def test_mutation_wrong_role_403(strict_client):
    ac, holder = strict_client
    holder.user = user_without_owner()
    # Baseline (principal_or_internal) satisfied by the internal token; the role
    # guard then rejects a caller lacking role.process.owner.
    r = await ac.post(
        "/packs/wire-repair-standard/1.0.0/deprecate", headers={INTERNAL_HEADER: INTERNAL}
    )
    assert r.status_code == 403
    assert r.json()["detail"]["missing_role"] == "role.process.owner"
