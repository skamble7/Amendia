"""
Smoke tests for ConfigForge service.

Requires a running MongoDB instance. Set MONGO_URI env var or use the default
(mongodb://localhost:27017). Tests use an isolated database that is dropped after.
"""
from __future__ import annotations

import os
import pytest
import anyio
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB", "ConfigForgeTest")

from app.main import app
from app.db.mongodb import get_db


@pytest.fixture(autouse=True)
async def clean_db():
    db = await get_db()
    yield
    await db.client.drop_database(db.name)


async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


async def test_create_and_resolve_llm_config():
    payload = {
        "env": "prod",
        "kind": "llm",
        "provider": "openai",
        "platform": "raina",
        "name": "primary",
        "description": "Test OpenAI config",
        "data": {
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.1,
            "api_key_ref": "literal:sk-test123",
        },
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Create
        res = await ac.post("/config/", json=payload)
        assert res.status_code == 201
        created = res.json()
        assert created["ref"] == "prod.llm.openai.raina.primary"
        assert created["kind"] == "llm"
        assert created["data"]["model"] == "gpt-4o"

        # Resolve by canonical ref
        res = await ac.get("/config/resolve/prod.llm.openai.raina.primary")
        assert res.status_code == 200
        assert res.json()["ref"] == "prod.llm.openai.raina.primary"

        # List with filter
        res = await ac.get("/config/", params={"kind": "llm", "env": "prod"})
        assert res.status_code == 200
        assert len(res.json()) == 1


async def test_duplicate_ref_returns_409():
    payload = {
        "env": "dev",
        "kind": "llm",
        "provider": "anthropic",
        "name": "default",
        "data": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res1 = await ac.post("/config/", json=payload)
        assert res1.status_code == 201

        res2 = await ac.post("/config/", json=payload)
        assert res2.status_code == 409


async def test_update_and_delete():
    payload = {
        "env": "dev",
        "kind": "llm",
        "provider": "openai",
        "name": "fast",
        "data": {"provider": "openai", "model": "gpt-4o-mini"},
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        created = (await ac.post("/config/", json=payload)).json()
        entry_id = created["id"]

        # Update description
        res = await ac.put(f"/config/{entry_id}", json={"description": "Updated"})
        assert res.status_code == 200
        assert res.json()["description"] == "Updated"

        # Delete
        res = await ac.delete(f"/config/{entry_id}")
        assert res.status_code == 204

        # Gone
        res = await ac.get(f"/config/{entry_id}")
        assert res.status_code == 404


async def test_resolve_unknown_ref_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/config/resolve/prod.llm.openai.nobody.nonexistent")
    assert res.status_code == 404
