# tests/conftest.py
"""Shared fixtures: in-memory fakes for the repo, publisher, and mongo.

The app is exercised via httpx AsyncClient with the repository/publisher/mongo
dependencies overridden — no live Mongo/Rabbit and no lifespan needed.
"""
from __future__ import annotations

from typing import List, Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.dal.exceptions_repo import DuplicateExceptionError
from app.deps import get_mongo, get_publisher, get_repo
from app.main import create_app
from app.models.envelope import StoredException


class FakeRepository:
    """In-memory stand-in for ExceptionRepository."""

    def __init__(self) -> None:
        self.store: dict[str, StoredException] = {}

    async def insert(self, stored: StoredException) -> StoredException:
        if stored.exception_id in self.store:
            raise DuplicateExceptionError(stored.exception_id)
        self.store[stored.exception_id] = stored
        return stored

    async def get(self, exception_id: str) -> Optional[StoredException]:
        return self.store.get(exception_id)

    async def list(
        self,
        *,
        exception_type: Optional[str] = None,
        status: Optional[str] = None,
        reason_code: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[StoredException]:
        items = list(self.store.values())
        if exception_type:
            items = [i for i in items if i.exception_type == exception_type]
        if status:
            items = [i for i in items if i.status == status]
        if reason_code:
            items = [i for i in items if reason_code in i.reason_codes]
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
