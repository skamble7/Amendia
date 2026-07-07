# tests/conftest.py
"""Shared fixtures: in-memory fakes for the repo, stub client, mongo, consumer.

The app is exercised via httpx AsyncClient with the dependencies overridden —
no live Mongo/Rabbit/HTTP and no lifespan needed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.deps import get_consumer, get_mongo, get_repo
from app.main import create_app
from app.models.ingestion import EventRef, IngestionRecord, IngestionStatus, StatusChange


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FakeRepository:
    def __init__(self) -> None:
        self.store: dict[str, IngestionRecord] = {}

    async def create_received(
        self, *, exception_id, tenant, exception_type, event: EventRef,
        detail, fetch_error=None,
    ) -> Optional[IngestionRecord]:
        if exception_id in self.store:
            return None
        now = _utcnow()
        record = IngestionRecord(
            exception_id=exception_id,
            tenant=tenant,
            exception_type=exception_type,
            event=event,
            exception_detail=detail,
            fetch_error=fetch_error,
            status=IngestionStatus.RECEIVED,
            status_history=[StatusChange(status=IngestionStatus.RECEIVED, at=now)],
            created_at=now,
            updated_at=now,
        )
        self.store[exception_id] = record
        return record

    async def get(self, exception_id: str) -> Optional[IngestionRecord]:
        return self.store.get(exception_id)

    async def list(
        self, *, tenant=None, exception_type=None, status=None, limit=50, offset=0,
    ) -> List[IngestionRecord]:
        items = list(self.store.values())
        if tenant:
            items = [i for i in items if i.tenant == tenant]
        if exception_type:
            items = [i for i in items if i.exception_type == exception_type]
        if status:
            items = [i for i in items if i.status.value == status]
        items.sort(key=lambda i: i.created_at, reverse=True)
        return items[offset : offset + limit]


class FakeStubClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    async def fetch_exception(self, exception_id: str) -> Dict[str, Any]:
        self.calls.append(exception_id)
        if self.fail:
            raise RuntimeError("stub unreachable")
        return {
            "exception_id": exception_id,
            "tenant": "bank-alpha",
            "exception_type": "unable_to_apply",
            "status": "open",
            "payment": {"msg_type": "pacs.008.001.10"},
        }


class FakeMongo:
    def __init__(self, ok: bool = True) -> None:
        self._ok = ok

    async def ping(self) -> bool:
        return self._ok


class FakeConsumer:
    def __init__(self, ready: bool = True) -> None:
        self.is_ready = ready


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def stub_client() -> FakeStubClient:
    return FakeStubClient()


@pytest.fixture
def mongo() -> FakeMongo:
    return FakeMongo()


@pytest.fixture
def consumer() -> FakeConsumer:
    return FakeConsumer()


@pytest_asyncio.fixture
async def client(repo, mongo, consumer):
    app = create_app()
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_mongo] = lambda: mongo
    app.dependency_overrides[get_consumer] = lambda: consumer
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
