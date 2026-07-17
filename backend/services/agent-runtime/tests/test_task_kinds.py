# tests/test_task_kinds.py
"""ADR-033 / Phase 2.7 — task-kind coverage: each BPMN task kind routes to an existing executor.

Retags seed tasks to the new kinds (keeping their bindings) and drives the REAL engine — a sendTask/
scriptTask/businessRuleTask runs via its capability, a manualTask is a manual HITL gate, and a
businessRuleTask's verdict drives a downstream exclusive gateway. No new executor code.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import MemorySaver

from amendia_bpmn import parse
from app.config import settings as app_settings
from app.dal.hitl_task_repo import HitlTaskRepository
from app.dal.instance_repo import ProcessInstanceRepository
from app.db.mongo import HITL_TASKS, PROCESS_INSTANCES, create_indexes
from app.engine.bundle import PackBundle
from app.engine.compiler import CompilerError, compile_graph
from app.engine.engine import ProcessEngine
from app.engine.executor import InProcessExecutor
from app.models.process_instance import InstanceStatus, ProcessInstance
from amendia_contracts.hitl_task import TaskStatus
from tests._wire import make_envelope, role_user

PK, PV = "wire-repair-standard", "1.0.0"


def _seed_xml() -> str:
    return (Path(app_settings.SEED_DIR) / "wire-repair.bpmn").read_text()


def _retag(xml: str, task_id: str, old: str, new: str) -> str:
    return re.sub(rf'<bpmn:{old} (id="{task_id}".*?)</bpmn:{old}>',
                  rf'<bpmn:{new} \1</bpmn:{new}>', xml, flags=re.DOTALL)


def _bundle(xml: str, retag_kinds: dict) -> PackBundle:
    """retag_kinds: {element_id: new_element_kind} — also updates the manifest binding element_kind."""
    b = PackBundle.from_seed_dir(app_settings.SEED_DIR)
    model, findings = parse(xml, b.manifest.process.process_id, profile="tasks")
    errs = [f.code for f in findings if f.severity == "error"]
    assert errs == [], errs
    b.bpmn_model = model
    b.bpmn_xml = xml
    for eid, kind in retag_kinds.items():
        for bd in b.manifest.bindings:
            if bd.element_id == eid:
                bd.element_kind = kind
    return b


class _Settings:
    EXECUTION_PROFILE = "tasks"
    SIMULATION_MODE = True
    SELF_BASE_URL = "http://rt"


class FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, doc, rk, mid):
        self.events.append((rk, doc))


@pytest_asyncio.fixture
async def harness():
    from mongomock_motor import AsyncMongoMockClient
    db = AsyncMongoMockClient()["amendia_test"]
    await create_indexes(db)
    instances = ProcessInstanceRepository(db[PROCESS_INSTANCES])
    hitl = HitlTaskRepository(db[HITL_TASKS])
    cp = MemorySaver()

    def build_engine(bundle):
        eng = ProcessEngine(registry=None, instance_repo=instances, hitl_repo=hitl, publisher=FakePublisher(),
                            settings=_Settings(), executor=InProcessExecutor(), checkpointer=cp)
        eng._bundles[(PK, PV)] = bundle
        eng._graphs[(PK, PV)] = compile_graph(bundle, eng._executor, simulation=True, checkpointer=cp, profile="tasks")
        return eng

    return {"instances": instances, "hitl": hitl, "build_engine": build_engine}


async def _start(engine, instances, pid, reason="AC01"):
    inst = ProcessInstance.new(process_instance_id=pid, exception_id=f"EXC-{pid}", pack_key=PK, pack_version=PV)
    await instances.insert(inst)
    await engine.start(inst, make_envelope(reason, exception_id=f"EXC-{pid}"))


async def _drive_to_completion(eng, hitl, instances, pid):
    for _ in range(20):
        inst = await instances.get(pid)
        if inst.status in (InstanceStatus.COMPLETED, InstanceStatus.FAILED):
            return inst
        t = (await hitl.list(process_instance_id=pid, status="open"))[0]
        dec = {"decision": "complete" if t.hitl_mode.value == "manual" else "approve",
               "decided_by": role_user(t.role)}
        await hitl.transition_status(t.task_id, expected_status=TaskStatus.OPEN, new_status=TaskStatus.DECIDED,
                                     set_fields={"decision": {**dec, "decided_at": "2026-07-17T12:00:00+00:00"}})
        await eng.resume(pid, dec, interrupt_id=t.interrupt_id)
    raise AssertionError("did not complete")


# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("kind", ["sendTask", "scriptTask", "businessRuleTask"])
async def test_capability_category_task_runs(harness, kind):
    # retag the autonomous Enrich serviceTask → each capability-category kind; it runs via its capability.
    xml = _retag(_seed_xml(), "Task_EnrichPayment", "serviceTask", kind)
    eng = harness["build_engine"](_bundle(xml, {"Task_EnrichPayment": kind}))
    instances = harness["instances"]
    pid = f"pi-{kind}"
    await _start(eng, instances, pid)
    assert (await instances.get(pid)).status == InstanceStatus.WAITING_HITL
    state = eng._graphs[(PK, PV)].get_state({"configurable": {"thread_id": pid}}).values
    assert "dossier" in state["artifacts"]   # the retagged task ran its capability


async def test_business_rule_task_verdict_drives_gateway(harness):
    # retag Assess (produces repair_verdict) → businessRuleTask; its verdict artifact drives
    # the downstream exclusive gateway and the AC01 path completes.
    xml = _retag(_seed_xml(), "Task_AssessRepairability", "serviceTask", "businessRuleTask")
    eng = harness["build_engine"](_bundle(xml, {"Task_AssessRepairability": "businessRuleTask"}))
    pid = "pi-rule"
    await _start(eng, harness["instances"], pid)
    final = await _drive_to_completion(eng, harness["hitl"], harness["instances"], pid)
    assert final.status == InstanceStatus.COMPLETED and final.outcome == "End_Resolved"


async def test_manual_task_is_a_manual_hitl_gate(harness):
    # retag the ApproveRepair userTask → manualTask; it remains a human/manual gate.
    xml = _retag(_seed_xml(), "Task_ApproveRepair", "userTask", "manualTask")
    eng = harness["build_engine"](_bundle(xml, {"Task_ApproveRepair": "manualTask"}))
    pid = "pi-manual"
    await _start(eng, harness["instances"], pid)
    final = await _drive_to_completion(eng, harness["hitl"], harness["instances"], pid)
    assert any(t.element_id == "Task_ApproveRepair" and t.hitl_mode.value == "manual"
               for t in await harness["hitl"].list(process_instance_id=pid))
    assert final.status == InstanceStatus.COMPLETED and final.outcome == "End_Resolved"


async def test_tasks_profile_guard():
    xml = _retag(_seed_xml(), "Task_EnrichPayment", "serviceTask", "sendTask")
    b = _bundle(xml, {"Task_EnrichPayment": "sendTask"})
    with pytest.raises(CompilerError):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(), profile="common_subset")
    compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(), profile="tasks")
