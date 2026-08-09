# tests/test_cohort_close.py
"""ADR-063 Phase 2 — ingestor branch: a close-classified message publishes CohortCloseRequested (not a
trigger dispatch) and marks the record terminal ``cohort_close``."""
from datetime import datetime, timezone

from app.models.events import IncomingTriggerRaisedEvent
from app.models.ingestion import IngestionStatus
from app.services.ingestion_service import IngestionService
from tests.conftest import FakePublisher, FakeRegistryClient, FakeRepository, FakeStubClient

ROUTING_KEY = "trigger_source.trigger_raised.v1"

_CLOSE_RESULT = {
    "kind": "cohort_close",
    "cohort_def_id": "wire_transfer_cohort",
    "correlation_value": "1v23p",
    "close_outcome": "process_ended",
}


def make_event(trigger_id="CLOSE-1"):
    return IncomingTriggerRaisedEvent(
        event_id="evt-close", occurred_at=datetime.now(timezone.utc),
        schema_version="pin.platform.trigger_raised/1.0", trigger_id=trigger_id,
        trigger_type="process_ended", fetch_url=f"http://localhost:8081/triggers/{trigger_id}")


def _svc(registry):
    repo, stub, pub = FakeRepository(), FakeStubClient(), FakePublisher()
    return IngestionService(repo, stub, registry, pub), repo, pub


async def test_close_classified_publishes_cohort_close_and_marks_terminal():
    svc, repo, pub = _svc(FakeRegistryClient(result=_CLOSE_RESULT))
    await svc.handle_event(make_event(), ROUTING_KEY)

    rec = await repo.get("CLOSE-1")
    assert rec.status is IngestionStatus.COHORT_CLOSE          # terminal, not dispatched
    assert rec.cohort_close["correlation_value"] == "1v23p"

    assert len(pub.published) == 1
    event, routing_key, _ = pub.published[0]
    assert routing_key == "ingestor.cohort_close_requested.v1"  # NOT trigger_dispatched
    assert event["correlation_value"] == "1v23p"
    assert event["close_outcome"] == "process_ended"
    assert event["cohort_def_id"] == "wire_transfer_cohort"
    assert event["trace"]["correlation_id"] == "CLOSE-1"


async def test_normal_trigger_still_dispatches_unchanged():
    # A result with no "kind" (default FakeRegistryClient) is a trigger → dispatch, exactly as before.
    svc, repo, pub = _svc(FakeRegistryClient())
    await svc.handle_event(make_event("EXC-1"), ROUTING_KEY)

    rec = await repo.get("EXC-1")
    assert rec.status is IngestionStatus.DISPATCHED
    assert pub.published[0][1] == "ingestor.trigger_dispatched.v1"


async def test_duplicate_close_delivery_publishes_once():
    svc, repo, pub = _svc(FakeRegistryClient(result=_CLOSE_RESULT))
    await svc.handle_event(make_event(), ROUTING_KEY)
    await svc._resolve_and_dispatch(await repo.get("CLOSE-1"))  # redelivery / sweep re-attempt
    assert len(pub.published) == 1                              # terminal guard blocked the second publish
