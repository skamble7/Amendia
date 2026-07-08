# tests/test_dispatch.py
"""Part A: resolve + dispatch, no_process, retry sweep, reply handling, guards."""
from datetime import datetime, timezone

from amendia_common.events import DISPATCH_ACCEPTED, DISPATCH_REJECTED
from app.models.events import IncomingExceptionRaisedEvent
from app.models.ingestion import IngestionStatus
from app.services.ingestion_service import IngestionService
from tests.conftest import (
    FakePublisher,
    FakeRegistryClient,
    FakeRepository,
    FakeStubClient,
)

ROUTING_KEY = "bank-alpha.stub_exception.exception_raised.v1"


def make_event(exception_id="EXC-2026-000123"):
    return IncomingExceptionRaisedEvent(
        event_id="evt-1",
        occurred_at=datetime.now(timezone.utc),
        schema_version="pin.payments.wire_exception/1.0",
        exception_id=exception_id,
        tenant="bank-alpha",
        exception_type="unable_to_apply",
        fetch_url=f"http://localhost:8081/exceptions/{exception_id}",
    )


def _svc(**kw):
    repo = kw.get("repo") or FakeRepository()
    stub = kw.get("stub") or FakeStubClient()
    registry = kw.get("registry") or FakeRegistryClient()
    pub = kw.get("pub") or FakePublisher()
    return IngestionService(repo, stub, registry, pub), repo, registry, pub


async def test_resolve_happy_path_dispatches_and_publishes():
    svc, repo, registry, pub = _svc()
    await svc.handle_event(make_event(), ROUTING_KEY)

    rec = await repo.get("EXC-2026-000123")
    assert rec.status is IngestionStatus.DISPATCHED
    assert rec.resolution.pack_key == "wire-repair-standard"
    assert rec.resolution.pack_version == "1.0.0"
    # one exception_dispatched event published with the right routing key + fields
    assert len(pub.published) == 1
    event, routing_key, _ = pub.published[0]
    assert routing_key == "bank-alpha.ingestor.exception_dispatched.v1"
    assert event["exception_id"] == "EXC-2026-000123"
    assert event["fetch_url"].endswith("/exceptions/EXC-2026-000123")
    assert event["resolution"]["pack_key"] == "wire-repair-standard"
    assert event["trace"]["correlation_id"] == "EXC-2026-000123"
    assert event["trace"]["causation_id"] == "evt-1"


async def test_no_match_transitions_no_process():
    svc, repo, registry, pub = _svc(registry=FakeRegistryClient(no_match=True))
    await svc.handle_event(make_event(), ROUTING_KEY)

    rec = await repo.get("EXC-2026-000123")
    assert rec.status is IngestionStatus.NO_PROCESS
    assert rec.no_match["considered_packs"] == 0
    assert pub.published == []


async def test_registry_unavailable_stays_received_then_sweep_dispatches():
    registry = FakeRegistryClient(unavailable=True)
    svc, repo, _, pub = _svc(registry=registry)
    await svc.handle_event(make_event(), ROUTING_KEY)

    rec = await repo.get("EXC-2026-000123")
    assert rec.status is IngestionStatus.RECEIVED
    assert pub.published == []

    # registry recovers → the sweep re-resolves and dispatches
    registry.unavailable = False
    dispatched = await svc.resolve_pending()
    assert dispatched == 1
    rec = await repo.get("EXC-2026-000123")
    assert rec.status is IngestionStatus.DISPATCHED
    assert len(pub.published) == 1


async def test_reply_accepted_transitions_and_stores_instance_id():
    svc, repo, _, _ = _svc()
    await svc.handle_event(make_event(), ROUTING_KEY)  # → dispatched

    await svc.handle_reply(
        {"exception_id": "EXC-2026-000123", "process_instance_id": "pi-1"},
        "bank-alpha.agent_runtime." + DISPATCH_ACCEPTED + ".v1",
    )
    rec = await repo.get("EXC-2026-000123")
    assert rec.status is IngestionStatus.ACCEPTED
    assert rec.process_instance_id == "pi-1"


async def test_reply_rejected_transitions_and_stores_reason():
    svc, repo, _, _ = _svc()
    await svc.handle_event(make_event(), ROUTING_KEY)  # → dispatched

    await svc.handle_reply(
        {"exception_id": "EXC-2026-000123", "reason": "unknown_pack", "detail": "no such pack"},
        "bank-alpha.agent_runtime." + DISPATCH_REJECTED + ".v1",
    )
    rec = await repo.get("EXC-2026-000123")
    assert rec.status is IngestionStatus.REJECTED
    assert rec.rejection.reason == "unknown_pack"


async def test_accepted_reply_before_dispatch_is_ignored():
    # A stray accepted reply for a record still in received must not corrupt state.
    repo = FakeRepository()
    svc, repo, _, _ = _svc(repo=repo, registry=FakeRegistryClient(unavailable=True))
    await svc.handle_event(make_event(), ROUTING_KEY)  # stuck received
    assert (await repo.get("EXC-2026-000123")).status is IngestionStatus.RECEIVED

    await svc.handle_reply(
        {"exception_id": "EXC-2026-000123", "process_instance_id": "pi-x"},
        "bank-alpha.agent_runtime." + DISPATCH_ACCEPTED + ".v1",
    )
    assert (await repo.get("EXC-2026-000123")).status is IngestionStatus.RECEIVED


async def test_duplicate_accepted_reply_is_noop():
    svc, repo, _, _ = _svc()
    await svc.handle_event(make_event(), ROUTING_KEY)
    key = "bank-alpha.agent_runtime." + DISPATCH_ACCEPTED + ".v1"
    await svc.handle_reply({"exception_id": "EXC-2026-000123", "process_instance_id": "pi-1"}, key)
    await svc.handle_reply({"exception_id": "EXC-2026-000123", "process_instance_id": "pi-1"}, key)
    rec = await repo.get("EXC-2026-000123")
    assert rec.status is IngestionStatus.ACCEPTED
    # exactly one accepted entry in the history (guard blocked the replay)
    accepted = [c for c in rec.status_history if c.status is IngestionStatus.ACCEPTED]
    assert len(accepted) == 1
