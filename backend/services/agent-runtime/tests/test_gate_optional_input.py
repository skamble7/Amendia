# tests/test_gate_optional_input.py
"""A HITL gate must not crash on an ABSENT OPTIONAL read-only input (surfaced by the loop-back-optionality fix), and
advancing to the next gate must fail the instance cleanly rather than 500 + orphan it in RUNNING.

Fix 1: _gate_artifacts omits a spec whose resolved data is None — a loop-back/branch input not produced on this path
has no context to show and must not reach the model as data:None (the HitlTask payload artifact requires a dict).
Fix 2: _run_segment brings the parking/materialization/completion dispatch under the same failure handling as the
node run, so an error advancing to the next gate routes to _fail instead of escaping to the HTTP caller.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest_asyncio
from langgraph.checkpoint.memory import MemorySaver
from mongomock_motor import AsyncMongoMockClient

from app.config import settings
from app.dal.hitl_task_repo import HitlTaskRepository
from app.dal.instance_repo import ProcessInstanceRepository
from app.db.mongo import HITL_TASKS, PROCESS_INSTANCES, create_indexes
from app.engine.engine import ProcessEngine
from app.engine.task_runner import IOSpec, _gate_artifacts
from app.models.process_instance import InstanceStatus, ProcessInstance
from tests._stub_stack import stub_executor


# --------------------------------------------------------------------------- #
# Fix 1 — _gate_artifacts omits an absent optional read-only input
# --------------------------------------------------------------------------- #
def test_gate_artifacts_omits_absent_optional_input_keeps_present_and_empty():
    specs = [IOSpec(name="prepared", schema_ref="art.p.prepared@1.0.0"),
             IOSpec(name="recovery", schema_ref="art.p.recovery@1.0.0")]
    # `recovery` resolved to None (optional, produced only on the SLA-breach branch — absent on the normal path).
    arts = _gate_artifacts(specs, {"prepared": {"tray": 3}, "recovery": None})

    assert [a["name"] for a in arts] == ["prepared"]           # absent optional omitted — never data:None
    assert arts[0]["data"] == {"tray": 3}
    assert all(a["data"] is not None for a in arts)
    # a PRESENT empty dict is a valid present artifact and is kept
    assert _gate_artifacts([IOSpec(name="notes", schema_ref="s")], {"notes": {}}) == \
        [{"name": "notes", "schema": "s", "data": {}}]


# --------------------------------------------------------------------------- #
# Fix 2 + advance — driving _run_segment through the next gate
# --------------------------------------------------------------------------- #
class _FakeGraph:
    """A graph whose invoke raises a single HITL interrupt carrying a crafted gate payload."""

    def __init__(self, gate_payload: dict) -> None:
        self._payload = gate_payload

    def invoke(self, _cmd, _cfg):
        return {"__interrupt__": [SimpleNamespace(id="int-1", value=self._payload)]}

    def get_state(self, _cfg):
        return SimpleNamespace(values={})


class _FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, event, routing_key, message_id):
        self.events.append((routing_key, event))


@pytest_asyncio.fixture
async def env():
    db = AsyncMongoMockClient()["amendia_test"]
    await create_indexes(db)
    instance_repo = ProcessInstanceRepository(db[PROCESS_INSTANCES])
    hitl_repo = HitlTaskRepository(db[HITL_TASKS])
    engine = ProcessEngine(
        registry=None, instance_repo=instance_repo, hitl_repo=hitl_repo,
        publisher=_FakePublisher(), settings=settings, executor=stub_executor(), checkpointer=MemorySaver())
    return engine, instance_repo, hitl_repo


async def _instance(instance_repo, pid="pi-opt"):
    inst = ProcessInstance.new(process_instance_id=pid, trigger_id="E-1",
                               pack_key="p", pack_version="1.0.0", correlation_id="E-1")
    await instance_repo.insert(inst)
    return inst


# the gate ServeOrder would surface AFTER the loop-back fix: `prepared` present, its human output empty-and-editable,
# and the absent-optional `recovery` already dropped by _gate_artifacts — so NO artifact carries data:None.
_GATE = {
    "element_id": "ServeOrder", "hitl_mode": "manual", "role": "role.p.server", "kind": "human", "title": "Serve order",
    "artifacts": [
        {"name": "prepared", "schema": "art.p.prepared@1.0.0", "data": {"tray": 3}},
        {"name": "order", "schema": "art.p.order@1.0.0", "data": {}, "draft": True, "authored_by_human": True},
    ],
}


async def test_run_segment_advances_to_a_gate_with_absent_optional_input(env):
    engine, instance_repo, hitl_repo = env
    inst = await _instance(instance_repo)

    await engine._run_segment(inst, _FakeGraph(_GATE), None)     # must NOT raise (no 500), no stuck RUNNING

    fresh = await instance_repo.get(inst.process_instance_id)
    assert fresh.status == InstanceStatus.WAITING_HITL           # parked at the next gate
    tasks = await hitl_repo.list(process_instance_id=inst.process_instance_id)
    assert len(tasks) == 1
    arts = {a.name: a for a in tasks[0].payload.artifacts}
    assert set(arts) == {"prepared", "order"}                    # `recovery` was omitted; no data:None reached the model
    assert arts["order"].data == {}                              # the human OUTPUT still surfaces with empty data


async def test_run_segment_fails_cleanly_if_advancing_raises(env):
    engine, instance_repo, hitl_repo = env
    inst = await _instance(instance_repo, pid="pi-bad")
    # a payload whose artifact carries data:None (the pre-fix crash shape) fails HitlTask validation while advancing.
    bad = {**_GATE, "artifacts": [{"name": "recovery", "schema": "art.p.recovery@1.0.0", "data": None}]}

    await engine._run_segment(inst, _FakeGraph(bad), None)       # must NOT raise out to the caller

    fresh = await instance_repo.get(inst.process_instance_id)
    assert fresh.status == InstanceStatus.FAILED                 # failed cleanly with a reason, not a 500 + orphan
    assert fresh.last_error
    assert await hitl_repo.list(process_instance_id=inst.process_instance_id) == []
