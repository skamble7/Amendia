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
        self, *, exception_id, exception_type, event: EventRef,
        detail, fetch_error=None,
    ) -> Optional[IngestionRecord]:
        if exception_id in self.store:
            return None
        now = _utcnow()
        record = IngestionRecord(
            exception_id=exception_id,
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
        self, *, exception_type=None, status=None, limit=50, offset=0,
    ) -> List[IngestionRecord]:
        items = list(self.store.values())
        if exception_type:
            items = [i for i in items if i.exception_type == exception_type]
        if status:
            items = [i for i in items if i.status.value == status]
        items.sort(key=lambda i: i.created_at, reverse=True)
        return items[offset : offset + limit]

    async def list_by_status(self, status: IngestionStatus, *, limit=200) -> List[IngestionRecord]:
        items = [i for i in self.store.values() if i.status is status]
        items.sort(key=lambda i: i.created_at)
        return items[:limit]

    # --- guarded lifecycle transitions (mirror the real repo) ---

    def _transition(self, exception_id, status, *, expected, detail=None, **fields):
        rec = self.store.get(exception_id)
        if rec is None or rec.status not in expected:
            return None
        rec.status = status
        rec.status_history.append(StatusChange(status=status, at=_utcnow(), detail=detail))
        rec.updated_at = _utcnow()
        for k, v in fields.items():
            setattr(rec, k, v)
        return rec

    async def mark_dispatched(self, exception_id, *, resolution, detail=None):
        from app.models.ingestion import ResolutionRef
        return self._transition(
            exception_id, IngestionStatus.DISPATCHED,
            expected={IngestionStatus.RECEIVED}, detail=detail,
            resolution=ResolutionRef(**resolution),
        )

    async def mark_no_process(self, exception_id, *, no_match, detail=None):
        return self._transition(
            exception_id, IngestionStatus.NO_PROCESS,
            expected={IngestionStatus.RECEIVED}, detail=detail, no_match=no_match,
        )

    async def mark_accepted(self, exception_id, *, process_instance_id, detail=None):
        return self._transition(
            exception_id, IngestionStatus.ACCEPTED,
            expected={IngestionStatus.DISPATCHED}, detail=detail,
            process_instance_id=process_instance_id,
        )

    async def mark_rejected(self, exception_id, *, rejection, detail=None):
        from app.models.ingestion import RejectionRef
        return self._transition(
            exception_id, IngestionStatus.REJECTED,
            expected={IngestionStatus.DISPATCHED}, detail=detail,
            rejection=RejectionRef(**rejection),
        )


class FakeRegistryClient:
    """Configurable resolve: return a match, raise no-match, or raise unavailable."""

    def __init__(self, result=None, *, no_match=False, unavailable=False):
        self.result = result or {
            "pack_key": "wire-repair-standard",
            "pack_version": "1.0.0",
            "rule_id": "wire-uta-repairable-codes",
            "resolved_at": "2026-07-07T00:00:00Z",
        }
        self.no_match = no_match
        self.unavailable = unavailable
        self.calls: list = []

    async def resolve(self, envelope):
        from app.clients.registry_client import RegistryNoMatch, RegistryUnavailable
        self.calls.append(envelope)
        if self.unavailable:
            raise RegistryUnavailable("registry down")
        if self.no_match:
            raise RegistryNoMatch({"detail": "no active pack matched", "considered_packs": 0})
        return self.result


class FakePublisher:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, event: dict, routing_key: str, message_id: str) -> None:
        self.published.append((event, routing_key, message_id))


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
    from amendia_auth import AuthContext
    from amendia_auth.settings import AuthSettings

    app = create_app()
    app.state.auth = AuthContext(AuthSettings(auth_disabled=True, internal_token="test-internal"))
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_mongo] = lambda: mongo
    app.dependency_overrides[get_consumer] = lambda: consumer
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
