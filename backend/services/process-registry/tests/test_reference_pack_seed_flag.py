# tests/test_reference_pack_seed_flag.py
"""ADR-052: SEED_REFERENCE_PACK gates the startup seed of the reference wire-repair-standard pack.

Default True keeps the existing seed behavior; False boots a clean, copilot-populated registry so the reference
pack's schemas/capabilities don't compete on triage. Exercises the real app lifespan (mongomock-backed) with the
seed step spied, so we assert the gate without needing a live Mongo or the full seed dataset.
"""
from __future__ import annotations

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.config import settings
from app.db.mongo import create_indexes
from app.main import create_app, lifespan


class _FakeMongo:
    """A mongomock-backed stand-in for app.db.mongo.MongoClient (same surface the lifespan uses)."""

    def __init__(self, uri: str, db_name: str) -> None:
        self._db = AsyncMongoMockClient()[db_name]

    async def connect(self) -> None:
        await create_indexes(self._db)

    @property
    def db(self):
        return self._db

    def collection(self, name: str):
        return self._db[name]

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


@pytest.fixture
def seed_env(monkeypatch):
    """Point the seed at a (spied) reference pack: SEED_ON_STARTUP + SEED_DIR set, Mongo faked, onboard spied."""
    monkeypatch.setattr("app.main.MongoClient", _FakeMongo)
    monkeypatch.setattr(settings, "SEED_ON_STARTUP", True)
    monkeypatch.setattr(settings, "SEED_DIR", "/seed/wire-repair-standard")
    calls = {"n": 0}

    async def _spy_onboard(*_a, **_k):
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr("app.seeding.onboard_seed.onboard", _spy_onboard)
    return calls


async def test_reference_pack_seed_skipped_when_flag_false(seed_env, monkeypatch, caplog):
    monkeypatch.setattr(settings, "SEED_REFERENCE_PACK", False)
    app = create_app()
    import logging
    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            assert seed_env["n"] == 0                            # the reference seed never ran
            assert await app.state.pack_repo.list() == []        # GET /packs would be empty — clean slate
    assert any("Reference pack seed skipped (SEED_REFERENCE_PACK=false)." in r.message for r in caplog.records)


async def test_reference_pack_seed_runs_when_flag_true(seed_env, monkeypatch):
    monkeypatch.setattr(settings, "SEED_REFERENCE_PACK", True)   # the default — unchanged behavior
    app = create_app()
    async with lifespan(app):
        assert seed_env["n"] == 1                                # the existing seed still runs
