# tests/test_messages_api.py
"""ADR-031 Phase 2.4 — the POST /messages intake maps engine outcomes to HTTP + requires an anchor.

The correlation logic itself is covered in test_messages.py; here we pin the HTTP contract with a
fake engine.
"""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient


class FakeEngine:
    def __init__(self):
        self.result = {"status": "delivered", "process_instance_id": "pi-x"}
        self.calls = []

    async def deliver_message(self, message_name, *, exception_id=None, correlation_id=None, payload=None):
        self.calls.append((message_name, exception_id, correlation_id, payload))
        return self.result


@pytest_asyncio.fixture
async def api():
    from amendia_auth import AuthContext
    from amendia_auth.settings import AuthSettings
    from app.main import create_app

    app = create_app()
    app.state.auth = AuthContext(AuthSettings(auth_disabled=True, internal_token="test-internal"))
    engine = FakeEngine()
    app.state.engine = engine
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, engine


async def test_delivered_returns_202(api):
    ac, engine = api
    r = await ac.post("/messages", json={"message_name": "rfi_reply", "exception_id": "EXC-1", "payload": {"a": 1}})
    assert r.status_code == 202 and r.json()["process_instance_id"] == "pi-x"
    assert engine.calls == [("rfi_reply", "EXC-1", None, {"a": 1})]


async def test_missing_anchor_is_422(api):
    ac, _ = api
    r = await ac.post("/messages", json={"message_name": "rfi_reply"})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "anchor_required"


async def test_no_match_is_404(api):
    ac, engine = api
    engine.result = {"status": "no_matching_subscription"}
    r = await ac.post("/messages", json={"message_name": "x", "exception_id": "EXC-1"})
    assert r.status_code == 404 and r.json()["detail"]["error"] == "no_matching_subscription"


async def test_duplicate_is_409(api):
    ac, engine = api
    engine.result = {"status": "already_consumed"}
    r = await ac.post("/messages", json={"message_name": "x", "correlation_id": "C-1"})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "already_consumed"


async def test_invalid_payload_is_422(api):
    ac, engine = api
    engine.result = {"status": "invalid_payload", "detail": "art.x invalid at '<root>'"}
    r = await ac.post("/messages", json={"message_name": "x", "exception_id": "EXC-1", "payload": {}})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "invalid_payload"
