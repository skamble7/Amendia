# tests/test_cohort_service.py
"""ADR-063 Phase 1 — join-on-spawn through DispatchService (the headline e2e).

Two segments sharing one ``correlation_value`` across two packs → exactly ONE cohort, both on the roster,
``opened`` once + ``member_joined`` twice. Absent key → standalone. Re-dispatch (idempotent instance) →
no double-join. A closed cohort → ``late_join``, no second cohort. A cohort_def_id mismatch → ``late_join``.
A non-member pack → no cohort at all.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient

from amendia_contracts.process_pack import CohortMembership
from app.dal.cohort_repo import CohortInstanceRepository
from app.dal.dispatch_repo import DispatchLogRepository
from app.dal.instance_repo import ProcessInstanceRepository
from app.db.mongo import COHORT_INSTANCES, DISPATCH_LOG, PROCESS_INSTANCES, create_indexes
from app.models.cohort_instance import CohortState
from app.services.cohort_service import CohortService
from app.services.dispatch_service import DispatchService

MEMBERSHIP = CohortMembership(cohort_def_id="wire_transfer_cohort", correlation_key="exception_id")


def _event(*, trigger_id, pack_key, correlation_id=None):
    return {
        "event_id": uuid.uuid4().hex,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "pin.platform.trigger_dispatched/1.0",
        "trigger_id": trigger_id,
        "trigger_type": "unable_to_apply",
        "fetch_url": f"http://stub/triggers/{trigger_id}",
        "resolution": {"pack_key": pack_key, "pack_version": "1.0.0", "rule_id": "r1"},
        "trace": {"correlation_id": correlation_id or trigger_id},
    }


class FakeStore:
    """Returns an envelope carrying the given correlation value under ``exception_id`` (the cohort key)."""
    def __init__(self, correlation_value="1v23p", *, drop_key=False):
        self._value = correlation_value
        self._drop_key = drop_key

    async def fetch(self, fetch_url):
        return {} if self._drop_key else {"exception_id": self._value, "reason_codes": ["AC01"]}


class FakeEngine:
    """load_bundle returns a bundle whose manifest carries the pack's cohort_membership (or None)."""
    def __init__(self, memberships=None):
        self._memberships = memberships or {}
        self.started = []

    async def load_bundle(self, pack_key, version):
        membership = self._memberships.get(pack_key, MEMBERSHIP)
        manifest = SimpleNamespace(cohort_membership=membership)
        return SimpleNamespace(manifest=manifest, trigger_schema=None)

    async def start(self, instance, envelope):
        self.started.append(instance)


class FakePublisher:
    is_ready = True  # so the fail-soft emit actually publishes (mirrors a connected broker)

    def __init__(self):
        self.events = []

    async def publish(self, event, routing_key, message_id):
        self.events.append(event)


@pytest_asyncio.fixture
async def wiring():
    db = AsyncMongoMockClient()["amendia_test"]
    await create_indexes(db)
    instance_repo = ProcessInstanceRepository(db[PROCESS_INSTANCES])
    dispatch_repo = DispatchLogRepository(db[DISPATCH_LOG])
    cohort_repo = CohortInstanceRepository(db[COHORT_INSTANCES])
    return SimpleNamespace(db=db, instance_repo=instance_repo, dispatch_repo=dispatch_repo, cohort_repo=cohort_repo)


def _svc(wiring, *, engine=None, store=None):
    pub = FakePublisher()
    cohort_service = CohortService(repo=wiring.cohort_repo, publisher=pub)
    svc = DispatchService(
        engine=engine or FakeEngine(), instance_repo=wiring.instance_repo, dispatch_repo=wiring.dispatch_repo,
        store_client=store or FakeStore(), publisher=pub, cohort_service=cohort_service,
    )
    return svc, pub


def _ops(pub, op):
    return [e for e in pub.events if e.get("op") == op]


async def test_two_segments_same_value_share_one_cohort(wiring):
    svc, pub = _svc(wiring, engine=FakeEngine(), store=FakeStore("1v23p"))
    await svc.handle(_event(trigger_id="EXC-A", pack_key="wire-repair-standard"))
    await svc.handle(_event(trigger_id="EXC-B", pack_key="wire-repair-agentic"))
    await asyncio.sleep(0)

    cohorts = [c async for c in wiring.db[COHORT_INSTANCES].find({})]
    assert len(cohorts) == 1                                   # exactly one cohort for the shared value
    roster = {m["pack_key"] for m in cohorts[0]["members"]}
    assert roster == {"wire-repair-standard", "wire-repair-agentic"}
    assert cohorts[0]["active_member_count"] == 2
    assert len(_ops(pub, "opened")) == 1                       # opened once
    assert len(_ops(pub, "member_joined")) == 2               # member_joined per segment

    # both instances carry the cohort backlink (→ engine.start stamps the root span)
    coh_id = cohorts[0]["cohort_instance_id"]
    for tid in ("EXC-A", "EXC-B"):
        inst = (await wiring.instance_repo.list(trigger_id=tid))[0]
        assert inst.cohort_instance_id == coh_id
        assert inst.cohort_correlation_value == "1v23p"


async def test_absent_correlation_key_runs_standalone(wiring):
    svc, pub = _svc(wiring, engine=FakeEngine(), store=FakeStore(drop_key=True))
    await svc.handle(_event(trigger_id="EXC-N", pack_key="wire-repair-standard"))
    await asyncio.sleep(0)

    assert [c async for c in wiring.db[COHORT_INSTANCES].find({})] == []  # no cohort
    inst = (await wiring.instance_repo.list(trigger_id="EXC-N"))[0]
    assert inst.cohort_instance_id is None                                # not joined
    assert not pub.events or all(e.get("op") is None for e in pub.events)


async def test_redispatch_does_not_double_join(wiring):
    svc, pub = _svc(wiring, engine=FakeEngine(), store=FakeStore("1v23p"))
    ev = _event(trigger_id="EXC-A", pack_key="wire-repair-standard")
    await svc.handle(ev)
    await svc.handle(ev)                                       # same (trigger, pack) → idempotent instance
    await asyncio.sleep(0)

    cohorts = [c async for c in wiring.db[COHORT_INSTANCES].find({})]
    assert len(cohorts) == 1
    assert len(cohorts[0]["members"]) == 1                     # joined once, not twice
    assert len(_ops(pub, "opened")) == 1
    assert len(_ops(pub, "member_joined")) == 1


async def test_late_sibling_of_closed_cohort_is_flagged_not_reopened(wiring):
    # Seed a CLOSED cohort for the value; a new member must attach to it (late_join), not open a second.
    await wiring.db[COHORT_INSTANCES].insert_one({
        "cohort_instance_id": "coh-closed1", "cohort_def_id": "wire_transfer_cohort",
        "correlation_value": "1v23p", "state": CohortState.CLOSED.value, "members": [],
        "active_member_count": 0, "opened_at": "2026-08-08T00:00:00Z", "updated_at": "2026-08-08T00:00:00Z",
        "closed_at": "2026-08-08T01:00:00Z", "close_outcome": "process_ended",
    })
    svc, pub = _svc(wiring, engine=FakeEngine(), store=FakeStore("1v23p"))
    await svc.handle(_event(trigger_id="EXC-LATE", pack_key="wire-repair-standard"))
    await asyncio.sleep(0)

    cohorts = [c async for c in wiring.db[COHORT_INSTANCES].find({})]
    assert len(cohorts) == 1                                   # NOT reopened
    assert cohorts[0]["cohort_instance_id"] == "coh-closed1"
    assert len(cohorts[0]["members"]) == 1                     # the late sibling attached
    assert len(_ops(pub, "late_join")) == 1
    assert len(_ops(pub, "opened")) == 0
    assert len(_ops(pub, "member_joined")) == 0


async def test_cohort_def_id_mismatch_is_flagged_late_join(wiring):
    # First member opens the cohort under def A; a second member (same value) declares def B → late_join,
    # and the cohort is NOT re-homed to B.
    engine = FakeEngine(memberships={
        "wire-repair-standard": CohortMembership(cohort_def_id="wire_transfer_cohort", correlation_key="exception_id"),
        "wire-repair-agentic": CohortMembership(cohort_def_id="other_cohort", correlation_key="exception_id"),
    })
    svc, pub = _svc(wiring, engine=engine, store=FakeStore("1v23p"))
    await svc.handle(_event(trigger_id="EXC-A", pack_key="wire-repair-standard"))
    await svc.handle(_event(trigger_id="EXC-B", pack_key="wire-repair-agentic"))
    await asyncio.sleep(0)

    cohorts = [c async for c in wiring.db[COHORT_INSTANCES].find({})]
    assert len(cohorts) == 1
    assert cohorts[0]["cohort_def_id"] == "wire_transfer_cohort"   # not re-homed to other_cohort
    assert len(_ops(pub, "opened")) == 1
    assert len(_ops(pub, "member_joined")) == 1                    # the first member
    assert len(_ops(pub, "late_join")) == 1                        # the mismatched second


def test_root_span_attrs_carry_cohort_tags_only_when_joined():
    # ADR-063: engine.start stamps the root span via ProcessEngine._instance_span_attrs. A cohort member's
    # span carries the amendia.cohort.* tags; a standalone segment's does not (keys omitted).
    from amendia_telemetry import conventions as C
    from app.engine.engine import ProcessEngine
    from app.models.process_instance import ProcessInstance

    member = ProcessInstance.new(process_instance_id="pi-m", trigger_id="t", pack_key="wire-repair-standard",
                                 pack_version="1.0.0")
    member.cohort_instance_id, member.cohort_def_id, member.cohort_correlation_value = (
        "coh-1", "wire_transfer_cohort", "1v23p")
    attrs = ProcessEngine._instance_span_attrs(member)
    assert attrs[C.COHORT_DEF_ID] == "wire_transfer_cohort"
    assert attrs[C.COHORT_INSTANCE_ID] == "coh-1"
    assert attrs[C.COHORT_CORRELATION_VALUE] == "1v23p"
    assert all(str(k).startswith("amendia.") for k in attrs)  # domain-neutrality gate

    standalone = ProcessInstance.new(process_instance_id="pi-s", trigger_id="t2",
                                     pack_key="wire-repair-standard", pack_version="1.0.0")
    plain = ProcessEngine._instance_span_attrs(standalone)
    assert C.COHORT_INSTANCE_ID not in plain and C.COHORT_DEF_ID not in plain  # no cohort tags


async def test_non_member_pack_never_touches_cohorts(wiring):
    # A pack with NO cohort_membership dispatches and runs exactly as before — no cohort rows, no backlink.
    engine = FakeEngine(memberships={"wire-repair-standard": None})
    svc, pub = _svc(wiring, engine=engine, store=FakeStore("1v23p"))
    await svc.handle(_event(trigger_id="EXC-STD", pack_key="wire-repair-standard"))
    await asyncio.sleep(0)

    assert [c async for c in wiring.db[COHORT_INSTANCES].find({})] == []
    inst = (await wiring.instance_repo.list(trigger_id="EXC-STD"))[0]
    assert inst.cohort_instance_id is None
    assert engine.started and engine.started[0].process_instance_id == inst.process_instance_id  # ran normally
