# tests/test_audit_events.py
"""ADR-058 Phase B — a full wire-repair run publishes the governed audit events (over amendia.events)
that glea-service persists: instance lifecycle, each HITL decide (decided_by + sod_satisfied), and each
artifact commit (schema_ref + authored_by_human) — every one carrying correlation_id + trace_id.
"""
from __future__ import annotations

import re

import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import MemorySaver

from amendia_telemetry import configure_telemetry
from app.config import settings
from app.dal.hitl_task_repo import HitlTaskRepository
from app.dal.instance_repo import ProcessInstanceRepository
from app.db.mongo import HITL_TASKS, PROCESS_INSTANCES, create_indexes
from app.engine.bundle import PackBundle
from app.engine.engine import ProcessEngine
from app.models.process_instance import InstanceStatus, ProcessInstance
from app.services.hitl_service import HitlDecisionService
from tests._stub_stack import stub_executor
from tests._wire import make_envelope, role_user


class FakePublisher:
    def __init__(self):
        self.events = []  # (routing_key, event_doc)

    async def publish(self, event, routing_key, message_id):
        self.events.append((routing_key, event))

    def of(self, kind: str):
        return [e for rk, e in self.events if rk.endswith(f".{kind}.v1")]


@pytest_asyncio.fixture
async def env():
    configure_telemetry("test-agent-runtime")  # real SDK provider ⇒ a real instance trace_id
    from mongomock_motor import AsyncMongoMockClient
    db = AsyncMongoMockClient()["amendia_test"]
    await create_indexes(db)
    instance_repo = ProcessInstanceRepository(db[PROCESS_INSTANCES])
    hitl_repo = HitlTaskRepository(db[HITL_TASKS])
    publisher = FakePublisher()
    engine = ProcessEngine(
        registry=None, instance_repo=instance_repo, hitl_repo=hitl_repo,
        publisher=publisher, settings=settings, executor=stub_executor(), checkpointer=MemorySaver(),
    )
    engine._bundles[("wire-repair-standard", "1.0.0")] = PackBundle.from_seed_dir(settings.SEED_DIR)
    hitl = HitlDecisionService(hitl_repo=hitl_repo, instance_repo=instance_repo, engine=engine, publisher=publisher)
    return engine, hitl, instance_repo, hitl_repo, publisher


async def _drive_to_completion(engine, hitl, instance_repo, hitl_repo, exception_id="EXC-AUDIT"):
    envelope = make_envelope("AC01", exception_id=exception_id, creditor_name="ACME LLC")
    inst = ProcessInstance.new(
        process_instance_id=f"pi-{exception_id}", trigger_id=exception_id,
        pack_key="wire-repair-standard", pack_version="1.0.0", correlation_id=exception_id,
    )
    await instance_repo.insert(inst)
    await engine.start(inst, envelope)
    for _ in range(20):
        cur = await instance_repo.get(inst.process_instance_id)
        if cur.status in (InstanceStatus.COMPLETED, InstanceStatus.FAILED):
            break
        tasks = await hitl_repo.list(status="open", process_instance_id=inst.process_instance_id)
        if not tasks:
            break
        task = tasks[0]
        user = role_user(task.role)
        await hitl.claim(task.task_id, actor_id=user, actor_roles={task.role})
        dec = "complete" if task.hitl_mode.value == "manual" else "approve"
        await hitl.decide(task.task_id, actor_id=user, decision=dec)
    return inst


_HEX32 = re.compile(r"^[0-9a-f]{32}$")


async def test_full_run_publishes_governed_audit_events(env):
    engine, hitl, instance_repo, hitl_repo, publisher = env
    inst = await _drive_to_completion(engine, hitl, instance_repo, hitl_repo)
    final = await instance_repo.get(inst.process_instance_id)
    assert final.status == InstanceStatus.COMPLETED

    # --- lifecycle: completed, with correlation_id + a real trace_id joining otel_traces ---
    completed = publisher.of("process_completed")
    assert len(completed) == 1
    tr = completed[0]["trace"]
    assert tr["correlation_id"] == "EXC-AUDIT"
    assert _HEX32.match(tr["trace_id"]), "process_completed must carry the instance trace_id"

    # --- each HITL decide: decided_by + sod_satisfied field + trace ---
    decided = publisher.of("hitl_task_decided")
    assert decided, "expected HITL decide audit events"
    for d in decided:
        assert d["decided_by"]
        assert "sod_satisfied" in d               # present (True when a four-eyes rule applied, else None)
        assert d["trace"]["correlation_id"] == "EXC-AUDIT"
        assert _HEX32.match(d["trace"]["trace_id"])

    # --- each artifact commit: schema_ref (pinned) + authored_by_human + trace ---
    committed = publisher.of("artifact_committed")
    assert committed, "expected artifact_committed audit events"
    for a in committed:
        assert re.match(r"^art\..+@\d+\.\d+\.\d+$", a["schema_ref"]), a["schema_ref"]
        assert a["artifact_key"]
        assert "authored_by_human" in a
        assert isinstance(a["authored_by_human"], bool)   # structural flag present on every commit
        assert _HEX32.match(a["trace"]["trace_id"])

    # --- domain-neutrality: no published governed event body leaks a pack/domain term as a KEY ---
    for _rk, ev in publisher.events:
        for key in ev.keys():
            assert "wire" not in key.lower() and "repair" not in key.lower()


async def test_audit_events_are_idempotent_across_republish(env):
    # Re-draining the same state must not mint new artifact_committed event_ids (glea dedupes on them).
    engine, hitl, instance_repo, hitl_repo, publisher = env
    inst = await _drive_to_completion(engine, hitl, instance_repo, hitl_repo, exception_id="EXC-IDEMP")
    first_ids = {a["event_id"] for a in publisher.of("artifact_committed")}
    # Force a re-drain from the final checkpoint with the high-water reset (simulates crash recovery).
    engine._audit_hw.pop(inst.process_instance_id, None)
    state = await engine.get_checkpoint_state(inst.process_instance_id, "wire-repair-standard", "1.0.0")
    await engine._drain_audit(inst, state)
    second_ids = {a["event_id"] for a in publisher.of("artifact_committed")}
    assert first_ids and first_ids <= second_ids
    # The republished ids are the SAME (stable event_id) — glea's ReplacingMergeTree collapses them.
    republished = [a for a in publisher.of("artifact_committed") if a["event_id"] in first_ids]
    assert len(republished) == 2 * len(first_ids)   # each original id emitted exactly twice, unchanged
