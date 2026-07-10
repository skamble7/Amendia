# tests/test_ingestion_service.py
from datetime import datetime, timezone

from app.events.rabbit import BINDING_KEY
from app.models.events import IncomingExceptionRaisedEvent
from app.models.ingestion import IngestionStatus
from app.services.ingestion_service import IngestionService
from tests.conftest import FakeRepository, FakeStubClient

ROUTING_KEY = "stub_exception.exception_raised.v1"


def make_event(exception_id="EXC-2026-000123"):
    return IncomingExceptionRaisedEvent(
        event_id="evt-1",
        occurred_at=datetime.now(timezone.utc),
        schema_version="pin.payments.wire_exception/1.0",
        exception_id=exception_id,
        exception_type="unable_to_apply",
        fetch_url=f"http://localhost:8081/exceptions/{exception_id}",
    )


def test_binding_key_shape():
    assert BINDING_KEY == "stub_exception.exception_raised.v1"


async def test_handle_event_creates_received_record_with_detail():
    repo, stub = FakeRepository(), FakeStubClient()
    svc = IngestionService(repo, stub)

    await svc.handle_event(make_event(), ROUTING_KEY)

    rec = await repo.get("EXC-2026-000123")
    assert rec is not None
    assert rec.status is IngestionStatus.RECEIVED
    assert rec.fetch_error is None
    assert rec.exception_detail["exception_id"] == "EXC-2026-000123"
    assert rec.event.routing_key == ROUTING_KEY
    assert stub.calls == ["EXC-2026-000123"]


async def test_handle_event_is_idempotent_on_redelivery():
    repo, stub = FakeRepository(), FakeStubClient()
    svc = IngestionService(repo, stub)

    await svc.handle_event(make_event(), ROUTING_KEY)
    await svc.handle_event(make_event(), ROUTING_KEY)  # redelivery

    assert len(repo.store) == 1


async def test_handle_event_records_fetch_error_but_still_logs():
    repo, stub = FakeRepository(), FakeStubClient(fail=True)
    svc = IngestionService(repo, stub)

    await svc.handle_event(make_event(), ROUTING_KEY)

    rec = await repo.get("EXC-2026-000123")
    assert rec is not None
    assert rec.status is IngestionStatus.RECEIVED
    assert rec.exception_detail is None
    assert "failed to fetch" in rec.fetch_error
