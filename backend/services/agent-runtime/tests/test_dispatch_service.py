# tests/test_dispatch_service.py
"""Part B: dispatch handling — idempotency, accept, and each rejection reason."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.dal.dispatch_repo import DispatchLogRepository
from app.dal.instance_repo import ProcessInstanceRepository
from app.db.mongo import DISPATCH_LOG, PROCESS_INSTANCES, create_indexes
from app.models.process_instance import InstanceStatus, ProcessInstance, compute_idempotency_key
from app.services.dispatch_service import DispatchService
from tests._wire import make_envelope


def _event(*, trigger_id="EXC-D1", fetch_url="http://stub/triggers/EXC-D1",
           pack_key="wire-repair-standard", pack_version="1.0.0", event_id=None):
    return {
        "event_id": event_id or uuid.uuid4().hex,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "pin.platform.trigger_dispatched/1.0",
        "trigger_id": trigger_id,
        "trigger_type": "unable_to_apply",
        "fetch_url": fetch_url,
        "resolution": {"pack_key": pack_key, "pack_version": pack_version, "rule_id": "r1"},
        "trace": {"correlation_id": trigger_id},
    }


class FakeStore:
    def __init__(self, envelope=None, fail=False):
        self.envelope = envelope or make_envelope("AC01", exception_id="EXC-D1")
        self.fail = fail

    async def fetch(self, fetch_url):
        if self.fail:
            raise RuntimeError("store unreachable")
        return self.envelope


class FakeEngine:
    def __init__(self, load_error=None, trigger_schema=None):
        self.load_error = load_error
        self.started = []
        self._trigger_schema = trigger_schema

    async def load_bundle(self, pack_key, version):
        if self.load_error:
            raise self.load_error
        # ADR-047 D1: the loaded bundle exposes the pack's declared trigger schema (or None → opaque).
        return SimpleNamespace(trigger_schema=self._trigger_schema)

    async def start(self, instance, envelope):
        self.started.append(instance.process_instance_id)


class FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, event, routing_key, message_id):
        self.events.append((routing_key, event))


def _routing_keys(pub):
    return [rk for rk, _ in pub.events]


@pytest_asyncio.fixture
async def repos():
    from mongomock_motor import AsyncMongoMockClient
    db = AsyncMongoMockClient()["amendia_test"]
    await create_indexes(db)
    return (
        ProcessInstanceRepository(db[PROCESS_INSTANCES]),
        DispatchLogRepository(db[DISPATCH_LOG]),
    )


def _svc(repos, *, engine=None, store=None, publisher=None):
    instance_repo, dispatch_repo = repos
    return DispatchService(
        engine=engine or FakeEngine(), instance_repo=instance_repo, dispatch_repo=dispatch_repo,
        store_client=store or FakeStore(), publisher=publisher or FakePublisher(),
    ), instance_repo


async def test_accept_creates_instance_and_starts(repos):
    pub = FakePublisher()
    engine = FakeEngine()
    svc, instance_repo = _svc(repos, engine=engine, publisher=pub)
    await svc.handle(_event())
    await asyncio.sleep(0)  # let the spawned engine.start task run
    # instance created + accepted published + execution started
    insts = await instance_repo.list(trigger_id="EXC-D1")
    assert len(insts) == 1
    assert any("dispatch_accepted" in rk for rk in _routing_keys(pub))
    assert engine.started == [insts[0].process_instance_id]


async def test_duplicate_dispatch_is_idempotent(repos):
    pub = FakePublisher()
    engine = FakeEngine()
    svc, instance_repo = _svc(repos, engine=engine, publisher=pub)
    await svc.handle(_event(event_id="e1"))
    await asyncio.sleep(0)
    first = (await instance_repo.list(trigger_id="EXC-D1"))[0].process_instance_id
    await svc.handle(_event(event_id="e2"))  # same (trigger, pack) → same instance
    await asyncio.sleep(0)
    insts = await instance_repo.list(trigger_id="EXC-D1")
    assert len(insts) == 1
    # second accept references the existing instance; execution started once
    assert engine.started == [first]
    accepts = [e for rk, e in pub.events if "dispatch_accepted" in rk]
    assert all(a["process_instance_id"] == first for a in accepts)


async def test_reject_fetch_failed(repos):
    pub = FakePublisher()
    svc, _ = _svc(repos, store=FakeStore(fail=True), publisher=pub)
    await svc.handle(_event())
    rej = [e for rk, e in pub.events if "dispatch_rejected" in rk]
    assert rej and rej[0]["reason"] == "fetch_failed"


async def test_reject_envelope_invalid(repos):
    # ADR-047 D1: the pack declares a trigger schema; an envelope that fails it is rejected (envelope_invalid).
    pub = FakePublisher()
    trigger = {"type": "object", "required": ["exception_id", "reason_codes"],
               "properties": {"reason_codes": {"type": "array"}}}
    bad_store = FakeStore(envelope={"not": "a valid envelope"})
    svc, _ = _svc(repos, engine=FakeEngine(trigger_schema=trigger), store=bad_store, publisher=pub)
    await svc.handle(_event())
    rej = [e for rk, e in pub.events if "dispatch_rejected" in rk]
    assert rej and rej[0]["reason"] == "envelope_invalid"


async def test_opaque_envelope_accepts_any_object_but_rejects_non_object(repos):
    # ADR-047 D1: a pack with NO declared trigger treats the envelope as opaque — any JSON object is accepted
    # (no wire-shape assumption), while a non-object is still rejected.
    pub = FakePublisher()
    ok_store = FakeStore(envelope={"anything": "goes", "shape": [1, 2]})
    svc, insts = _svc(repos, engine=FakeEngine(), store=ok_store, publisher=pub)  # trigger_schema=None → opaque
    await svc.handle(_event())
    assert not [e for rk, e in pub.events if "dispatch_rejected" in rk]           # accepted
    assert any("dispatch_accepted" in rk for rk in _routing_keys(pub))

    pub2 = FakePublisher()
    svc2, _ = _svc(repos, engine=FakeEngine(), store=FakeStore(envelope=["not", "an", "object"]), publisher=pub2)
    await svc2.handle(_event(trigger_id="EXC-NONOBJ"))
    rej = [e for rk, e in pub2.events if "dispatch_rejected" in rk]
    assert rej and rej[0]["reason"] == "envelope_invalid"


async def test_reject_unknown_pack(repos):
    from app.clients.registry_client import RegistryNotFound
    pub = FakePublisher()
    svc, _ = _svc(repos, engine=FakeEngine(load_error=RegistryNotFound("x")), publisher=pub)
    await svc.handle(_event())
    rej = [e for rk, e in pub.events if "dispatch_rejected" in rk]
    assert rej and rej[0]["reason"] == "unknown_pack"


async def test_reject_pack_not_active(repos):
    from app.engine.engine import PackNotActive
    pub = FakePublisher()
    svc, _ = _svc(repos, engine=FakeEngine(load_error=PackNotActive("wire-repair-standard", "1.0.0", "draft")),
                  publisher=pub)
    await svc.handle(_event())
    rej = [e for rk, e in pub.events if "dispatch_rejected" in rk]
    assert rej and rej[0]["reason"] == "pack_not_active"


async def test_reject_pack_requires_profile(repos):
    # ADR-027 Phase 2.5: a common_subset runtime handed a parallel-profile pack refuses at load
    # with a distinct reason (not a generic unknown_pack / compiler error).
    from app.engine.engine import PackRequiresProfile
    pub = FakePublisher()
    svc, instance_repo = _svc(
        repos,
        engine=FakeEngine(load_error=PackRequiresProfile(
            "wire-repair-standard", "1.0.0", "parallel", "common_subset")),
        publisher=pub,
    )
    await svc.handle(_event())
    rej = [e for rk, e in pub.events if "dispatch_rejected" in rk]
    assert rej and rej[0]["reason"] == "pack_requires_profile"
    assert "parallel" in rej[0]["detail"]
    # refused before any instance was created
    assert await instance_repo.list(trigger_id="EXC-D1") == []
