# tests/test_auth.py
"""Targeted enforcement tests: reads require a principal, and claim/decide require
a bearer — identity is never taken from the request body (the stub is gone)."""
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
    r = await strict_client.get("/hitl-tasks")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Bearer")


async def test_claim_requires_bearer(strict_client):
    # No identity is accepted from the body — a missing bearer yields 401.
    r = await strict_client.post("/hitl-tasks/whatever/claim", json={})
    assert r.status_code == 401


async def test_decide_requires_bearer(strict_client):
    r = await strict_client.post("/hitl-tasks/whatever/decide", json={"decision": "approve"})
    assert r.status_code == 401
