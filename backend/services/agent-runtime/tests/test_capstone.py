# tests/test_capstone.py
"""ADR-034 / Phase 2.8 — capstone: several constructs COMPOSED in one runnable graph, driven end to
end under the flipped default (common_executable). Combines an embedded sub-process, a business-rule
task (verdict → gateway), a send task, an interrupting SLA timer boundary on a HITL gate, and an
error boundary — proving they coexist. (Each construct's exhaustive paths are covered per-phase.)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import MemorySaver

from amendia_bpmn import parse, required_profile
from app.config import settings as app_settings
from app.dal.hitl_task_repo import HitlTaskRepository
from app.dal.instance_repo import ProcessInstanceRepository
from app.dal.timer_repo import TimerRepository
from app.db.mongo import HITL_TASKS, PROCESS_INSTANCES, TIMERS, create_indexes
from app.engine.bundle import PackBundle
from app.engine.compiler import CompilerError, compile_graph
from app.engine.engine import ProcessEngine
from app.engine.executor import InProcessExecutor
from app.models.process_instance import InstanceStatus, ProcessInstance
from app.services.timer_service import TimerService
from amendia_contracts.hitl_task import TaskStatus
from tests._wire import make_envelope, role_user

PK, PV = "wire-repair-standard", "1.0.0"
_T0 = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.t = _T0

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


def _wrap_in_subprocess(xml, task_id, sub_id="Sub"):
    m = re.search(rf'<bpmn:serviceTask id="{task_id}".*?</bpmn:serviceTask>', xml, re.DOTALL)
    block = m.group(0)
    xml = xml.replace(block, "")
    xml = re.sub(rf'(targetRef=")({task_id})(")', r'\1' + sub_id + r'\3', xml)
    xml = re.sub(rf'(sourceRef=")({task_id})(")', r'\1' + sub_id + r'\3', xml)
    sub = (f'<bpmn:subProcess id="{sub_id}">'
           '<bpmn:startEvent id="SubStart"><bpmn:outgoing>subin</bpmn:outgoing></bpmn:startEvent>'
           + block +
           '<bpmn:endEvent id="SubEnd"><bpmn:incoming>subout</bpmn:incoming></bpmn:endEvent>'
           f'<bpmn:sequenceFlow id="subin" sourceRef="SubStart" targetRef="{task_id}"/>'
           f'<bpmn:sequenceFlow id="subout" sourceRef="{task_id}" targetRef="SubEnd"/></bpmn:subProcess>')
    return xml.replace("</bpmn:process>", sub + "</bpmn:process>")


def _retag(xml, task_id, old, new):
    return re.sub(rf'<bpmn:{old} (id="{task_id}".*?)</bpmn:{old}>',
                  rf'<bpmn:{new} \1</bpmn:{new}>', xml, flags=re.DOTALL)


def _capstone_xml() -> str:
    xml = (Path(app_settings.SEED_DIR) / "wire-repair.bpmn").read_text()
    xml = _wrap_in_subprocess(xml, "Task_EnrichPayment")          # embedded sub-process
    xml = _retag(xml, "Task_AssessRepairability", "serviceTask", "businessRuleTask")  # verdict → gateway
    xml = _retag(xml, "Task_NotifyParties", "serviceTask", "sendTask")                # send task
    # interrupting SLA timer boundary on the ApproveRepair HITL gate → escalation end
    xml = xml.replace("</bpmn:process>",
        '<bpmn:boundaryEvent id="Sla" attachedToRef="Task_ApproveRepair" cancelActivity="true">'
        '<bpmn:timerEventDefinition><bpmn:timeDuration>PT4H</bpmn:timeDuration></bpmn:timerEventDefinition>'
        '</bpmn:boundaryEvent><bpmn:sequenceFlow id="sla_esc" sourceRef="Sla" targetRef="End_Returned"/>'
        "</bpmn:process>")
    # error boundary on the ApplyRepair capability → rejection end
    xml = xml.replace("</bpmn:process>",
        '<bpmn:boundaryEvent id="ErrB" attachedToRef="Task_ApplyRepair">'
        '<bpmn:errorEventDefinition errorRef="ErrRej"/></bpmn:boundaryEvent>'
        '<bpmn:sequenceFlow id="err_esc" sourceRef="ErrB" targetRef="End_Returned"/></bpmn:process>')
    xml = xml.replace("</bpmn:definitions>",
                      '<bpmn:error id="ErrRej" errorCode="PAYMENT_REJECTED"/></bpmn:definitions>')
    return xml


def _bundle():
    b = PackBundle.from_seed_dir(app_settings.SEED_DIR)
    xml = _capstone_xml()
    model, findings = parse(xml, b.manifest.process.process_id, profile="common_executable")
    assert [f.code for f in findings if f.severity == "error"] == [], \
        [f.code for f in findings if f.severity == "error"]
    b.bpmn_model = model
    b.bpmn_xml = xml
    for bd in b.manifest.bindings:
        if bd.element_id == "Task_AssessRepairability":
            bd.element_kind = "businessRuleTask"
        elif bd.element_id == "Task_NotifyParties":
            bd.element_kind = "sendTask"
    return b


class _Settings:
    EXECUTION_PROFILE = "common_executable"
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
    clock = Clock()
    timers = TimerService(TimerRepository(db[TIMERS]), now=clock)
    cp = MemorySaver()
    b = _bundle()
    eng = ProcessEngine(registry=None, instance_repo=instances, hitl_repo=hitl, publisher=FakePublisher(),
                        settings=_Settings(), executor=InProcessExecutor(), checkpointer=cp, timer_service=timers)
    eng._bundles[(PK, PV)] = b
    eng._graphs[(PK, PV)] = compile_graph(b, eng._executor, simulation=True, checkpointer=cp,
                                          profile="common_executable")
    return {"eng": eng, "instances": instances, "hitl": hitl, "clock": clock, "bundle": b}


def test_capstone_pins_common_executable_and_refuses_common_subset():
    b = _bundle()
    assert required_profile(b.bpmn_model) == "common_executable"
    # a common_subset runtime refuses the composed pack at compile
    with pytest.raises(CompilerError):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(), profile="common_subset")
    # a common_executable runtime compiles it
    compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(), profile="common_executable")


async def test_capstone_composed_happy_path_runs_end_to_end(harness):
    eng, instances, hitl = harness["eng"], harness["instances"], harness["hitl"]
    pid = "pi-cap"
    inst = ProcessInstance.new(process_instance_id=pid, exception_id="EXC-cap", pack_key=PK, pack_version=PV)
    await instances.insert(inst)
    await eng.start(inst, make_envelope("AC01", exception_id="EXC-cap"))

    # drive every gate (human on time, so the SLA timer never fires) to completion
    for _ in range(20):
        cur = await instances.get(pid)
        if cur.status in (InstanceStatus.COMPLETED, InstanceStatus.FAILED):
            break
        t = (await hitl.list(process_instance_id=pid, status="open"))[0]
        dec = {"decision": "complete" if t.hitl_mode.value == "manual" else "approve",
               "decided_by": role_user(t.role)}
        await hitl.transition_status(t.task_id, expected_status=TaskStatus.OPEN, new_status=TaskStatus.DECIDED,
                                     set_fields={"decision": {**dec, "decided_at": _T0.isoformat()}})
        await eng.resume(pid, dec, interrupt_id=t.interrupt_id)

    final = await instances.get(pid)
    assert final.status == InstanceStatus.COMPLETED and final.outcome == "End_Resolved"
    # the sub-process's nested Enrich ran; the business-rule verdict drove the gateway; the send task ran
    state = harness["eng"]._graphs[(PK, PV)].get_state({"configurable": {"thread_id": pid}}).values
    assert {"dossier", "beneficiary", "repair"} <= set(state["artifacts"])
