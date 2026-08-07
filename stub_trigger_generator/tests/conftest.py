# tests/conftest.py
"""Shared fixtures: in-memory fakes for the single trigger repo, publisher, and mongo (ADR-059).

The app is exercised via httpx AsyncClient with the repository/publisher/mongo dependencies overridden —
no live Mongo/Rabbit and no lifespan needed.
"""
from __future__ import annotations

from typing import List, Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.dal.trigger_repo import DuplicateTriggerError
from app.deps import get_mongo, get_publisher, get_repo
from app.main import create_app
from app.models.trigger import StoredTrigger


class FakeRepository:
    """In-memory stand-in for the single TriggerRepository (domain-blind)."""

    def __init__(self) -> None:
        self.store: dict[str, StoredTrigger] = {}

    async def insert(self, stored: StoredTrigger) -> StoredTrigger:
        if stored.trigger_id in self.store:
            raise DuplicateTriggerError(stored.trigger_id)
        self.store[stored.trigger_id] = stored
        return stored

    async def get(self, trigger_id: str) -> Optional[StoredTrigger]:
        return self.store.get(trigger_id)

    async def list(
        self,
        *,
        trigger_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[StoredTrigger]:
        items = list(self.store.values())
        if trigger_type:
            items = [i for i in items if i.trigger_type == trigger_type]
        if status:
            items = [i for i in items if i.payload.get("status") == status]
        items.sort(key=lambda i: i.created_at, reverse=True)
        return items[offset : offset + limit]


class FakePublisher:
    """Records published messages; can be flipped to fail."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[str, str, dict]] = []
        self.is_ready = True

    async def publish(self, event: dict, routing_key: str, message_id: str) -> None:
        if self.fail:
            raise RuntimeError("simulated broker failure")
        self.published.append((routing_key, message_id, event))


class FakeMongo:
    def __init__(self, ok: bool = True) -> None:
        self._ok = ok

    async def ping(self) -> bool:
        return self._ok


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def mongo() -> FakeMongo:
    return FakeMongo()


@pytest_asyncio.fixture
async def client(repo, publisher, mongo):
    from amendia_auth import AuthContext
    from amendia_auth.settings import AuthSettings

    app = create_app()
    app.state.auth = AuthContext(AuthSettings(auth_disabled=True, internal_token="test-internal"))
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_publisher] = lambda: publisher
    app.dependency_overrides[get_mongo] = lambda: mongo
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
