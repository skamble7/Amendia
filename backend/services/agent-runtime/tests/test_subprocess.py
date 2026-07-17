# tests/test_subprocess.py
"""ADR-032 / Phase 2.6 — embedded sub-process: inline-flatten + substrate reuse inside a scope.

Wraps existing seed tasks in a sub-process (their bindings are unchanged — element ids are stable)
and drives the REAL engine, proving a nested serviceTask, a nested HITL gate, etc. behave exactly as
at top level because the compiler flattens the scope into one graph.
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
from app.dal.message_repo import MessageSubscriptionRepository, PendingMessageRepository
from app.dal.timer_repo import TimerRepository
from app.db.mongo import (
    HITL_TASKS,
    MESSAGE_SUBSCRIPTIONS,
    PENDING_MESSAGES,
    PROCESS_INSTANCES,
    TIMERS,
    create_indexes,
)
from app.engine.bundle import PackBundle
from app.engine.compiler import CompilerError, compile_graph
from app.engine.engine import ProcessEngine
from app.engine.executor import InProcessExecutor
from app.models.process_instance import InstanceStatus, ProcessInstance
from app.services.message_service import MessageSubscriptionService
from app.services.timer_service import TimerService
from amendia_contracts.hitl_task import TaskStatus
from tests._wire import make_envelope, role_user

PK, PV = "wire-repair-standard", "1.0.0"


def _seed_xml() -> str:
    return (Path(app_settings.SEED_DIR) / "wire-repair.bpmn").read_text()


def _wrap_in_subprocess(xml: str, task_id: str, sub_id: str = "Sub") -> str:
    """Move a top-level serviceTask/userTask into a new embedded sub-process (start → task → end),
    rewiring the parent flows to the sub-process box. The task keeps its element id (and binding)."""
    m = re.search(rf'<bpmn:(serviceTask|userTask) id="{task_id}".*?</bpmn:\1>', xml, re.DOTALL)
    block = m.group(0)
    xml = xml.replace(block, "")
    # parent flows in/out of the task → in/out of the sub-process box
    xml = re.sub(rf'(<bpmn:sequenceFlow id="[^"]+"[^>]*targetRef=")({task_id})(")', rf'\g<1>{sub_id}\3', xml)
    xml = re.sub(rf'(<bpmn:sequenceFlow id="[^"]+"[^>]*sourceRef=")({task_id})(")', rf'\g<1>{sub_id}\3', xml)
    sub = (
        f'<bpmn:subProcess id="{sub_id}" name="{sub_id}">'
        '<bpmn:startEvent id="SubStart"><bpmn:outgoing>subin</bpmn:outgoing></bpmn:startEvent>'
        + block +
        '<bpmn:endEvent id="SubEnd"><bpmn:incoming>subout</bpmn:incoming></bpmn:endEvent>'
        f'<bpmn:sequenceFlow id="subin" sourceRef="SubStart" targetRef="{task_id}"/>'
        f'<bpmn:sequenceFlow id="subout" sourceRef="{task_id}" targetRef="SubEnd"/>'
        '</bpmn:subProcess>')
    return xml.replace("</bpmn:process>", sub + "</bpmn:process>")


def _bundle(xml: str, *, drop_binding: str = None) -> PackBundle:
    b = PackBundle.from_seed_dir(app_settings.SEED_DIR)
    model, findings = parse(xml, b.manifest.process.process_id, profile="subprocess")
    errs = [f.code for f in findings if f.severity == "error"]
    assert errs == [], errs
    b.bpmn_model = model
    b.bpmn_xml = xml
    if drop_binding:  # simulate a missing binding for a nested task
        b.manifest.bindings = [bd for bd in b.manifest.bindings if bd.element_id != drop_binding]
        b.resolution["bindings"] = [rb for rb in b.resolution["bindings"] if rb["element_id"] != drop_binding]
    return b


class _Settings:
    EXECUTION_PROFILE = "subprocess"
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
    timers = TimerService(TimerRepository(db[TIMERS]))
    messages = MessageSubscriptionService(
        MessageSubscriptionRepository(db[MESSAGE_SUBSCRIPTIONS]),
        PendingMessageRepository(db[PENDING_MESSAGES]))
    cp = MemorySaver()

    def build_engine(bundle):
        eng = ProcessEngine(registry=None, instance_repo=instances, hitl_repo=hitl, publisher=FakePublisher(),
                            settings=_Settings(), executor=InProcessExecutor(), checkpointer=cp,
                            timer_service=timers, message_service=messages)
        eng._bundles[(PK, PV)] = bundle
        eng._graphs[(PK, PV)] = compile_graph(bundle, eng._executor, simulation=True,
                                              checkpointer=cp, profile="subprocess")
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

async def test_nested_service_task_runs_inline(harness):
    # wrap the autonomous Enrich serviceTask in a sub-process → it still runs (dossier committed),
    # then flows out of the box to the Assess gate.
    eng = harness["build_engine"](_bundle(_wrap_in_subprocess(_seed_xml(), "Task_EnrichPayment")))
    instances, hitl = harness["instances"], harness["hitl"]
    pid = "pi-sp1"
    await _start(eng, instances, pid)
    assert (await instances.get(pid)).status == InstanceStatus.WAITING_HITL
    nxt = (await hitl.list(process_instance_id=pid, status="open"))[0]
    assert nxt.element_id == "Task_AssessRepairability"
    state = eng._graphs[(PK, PV)].get_state({"configurable": {"thread_id": pid}}).values
    assert "dossier" in state["artifacts"]   # the NESTED task produced its artifact


async def test_wrapped_flow_runs_to_completion(harness):
    # the whole AC01 path still completes end to end with a task wrapped in a sub-process (inline).
    eng = harness["build_engine"](_bundle(_wrap_in_subprocess(_seed_xml(), "Task_EnrichPayment")))
    pid = "pi-sp2"
    await _start(eng, harness["instances"], pid)
    final = await _drive_to_completion(eng, harness["hitl"], harness["instances"], pid)
    assert final.status == InstanceStatus.COMPLETED and final.outcome == "End_Resolved"


async def test_nested_hitl_gate_behaves_like_top_level(harness):
    # a HITL gate (Task_ApproveRepair, manual) INSIDE a sub-process materializes + resumes normally.
    eng = harness["build_engine"](_bundle(_wrap_in_subprocess(_seed_xml(), "Task_ApproveRepair")))
    instances, hitl = harness["instances"], harness["hitl"]
    pid = "pi-sp3"
    await _start(eng, instances, pid)
    # drive to the nested gate and confirm it parked WAITING_HITL inside the sub-process
    final = await _drive_to_completion(eng, hitl, instances, pid)
    assert any(t.element_id == "Task_ApproveRepair" for t in await hitl.list(process_instance_id=pid))
    assert final.status == InstanceStatus.COMPLETED and final.outcome == "End_Resolved"


async def test_profile_guard_refuses_subprocess_under_lower_runtime():
    b = _bundle(_wrap_in_subprocess(_seed_xml(), "Task_EnrichPayment"))
    with pytest.raises(CompilerError):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(), profile="common_subset")
    # runs on a subprocess runtime
    compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(), profile="subprocess")


async def test_nested_unbound_task_fails_compile():
    # a nested task with no binding joins the bijection → the compiler refuses (unbound).
    xml = _wrap_in_subprocess(_seed_xml(), "Task_EnrichPayment")
    b = _bundle(xml, drop_binding="Task_EnrichPayment")
    with pytest.raises(CompilerError, match="unbound"):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(), profile="subprocess")


async def test_nested_two_level_compiles_and_starts(harness):
    # wrap Enrich in Sub, then wrap that whole sub-process in an outer sub-process (2 levels deep).
    xml = _wrap_in_subprocess(_seed_xml(), "Task_EnrichPayment", sub_id="Sub")
    # wrap the Sub box inside Sub2 by moving the <subProcess id="Sub"> block
    m = re.search(r'<bpmn:subProcess id="Sub".*?</bpmn:subProcess>', xml, re.DOTALL)
    block = m.group(0)
    xml = xml.replace(block, "")
    xml = re.sub(r'(targetRef=")Sub(")', r'\1Sub2\2', xml)
    xml = re.sub(r'(sourceRef=")Sub(")', r'\1Sub2\2', xml)
    outer = (
        '<bpmn:subProcess id="Sub2" name="Sub2">'
        '<bpmn:startEvent id="S2"><bpmn:outgoing>o1</bpmn:outgoing></bpmn:startEvent>'
        + block +
        '<bpmn:endEvent id="E2"><bpmn:incoming>o2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="o1" sourceRef="S2" targetRef="Sub"/>'
        '<bpmn:sequenceFlow id="o2" sourceRef="Sub" targetRef="E2"/>'
        '</bpmn:subProcess>')
    xml = xml.replace("</bpmn:process>", outer + "</bpmn:process>")
    b = _bundle(xml)
    assert set(b.bpmn_model.subprocesses) == {"Sub", "Sub2"}
    eng = harness["build_engine"](b)
    pid = "pi-sp4"
    await _start(eng, harness["instances"], pid)
    # the doubly-nested Enrich ran; parked at the next gate
    assert (await harness["instances"].get(pid)).status == InstanceStatus.WAITING_HITL
