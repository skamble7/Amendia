# tests/test_auth.py
"""Targeted enforcement test (strict auth): generate requires an authenticated
principal; the internal token is accepted for service-to-service fetch-back."""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from amendia_auth import AuthContext
from amendia_auth.resolver import INTERNAL_HEADER
from amendia_auth.settings import AuthSettings

from app.main import create_app

INTERNAL = "test-internal"


@pytest_asyncio.fixture
async def strict_client(repo, publisher, mongo):
    from app.deps import get_mongo, get_publisher, get_repo

    app = create_app()
    app.state.auth = AuthContext(AuthSettings(issuer="t", internal_token=INTERNAL))
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_publisher] = lambda: publisher
    app.dependency_overrides[get_mongo] = lambda: mongo
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_generate_unauthenticated_401(strict_client):
    r = await strict_client.post("/exceptions/generate")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Bearer")


async def test_internal_token_fetchback_ok(strict_client):
    # Generate one via the internal token (service-to-service), then fetch it back.
    gen = await strict_client.post("/exceptions/generate", headers={INTERNAL_HEADER: INTERNAL})
    assert gen.status_code == 201
    exc_id = gen.json()["created"][0]["exception"]["exception_id"]
    got = await strict_client.get(f"/exceptions/{exc_id}", headers={INTERNAL_HEADER: INTERNAL})
    assert got.status_code == 200
