# tests/test_auth.py
"""Targeted enforcement test (strict auth): reads require an authenticated principal."""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from amendia_auth import AuthContext
from amendia_auth.settings import AuthSettings

from app.main import create_app


@pytest_asyncio.fixture
async def strict_client():
    app = create_app()
    app.state.auth = AuthContext(AuthSettings(issuer="t", internal_token="test-internal"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_unauthenticated_read_401(strict_client):
    r = await strict_client.get("/ingestions")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Bearer")
