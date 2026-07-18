# tests/test_timers.py
"""ADR-027 Phase 2.2 — timer substrate end-to-end (deterministic, injected clock, no sleeps).

Drives the REAL ProcessEngine (+ mongomock repos, MemorySaver, InProcessExecutor) over the seed
BPMN transformed to add (a) a timer intermediate-catch and (b) an interrupting SLA boundary on the
``Task_ApproveRepair`` HITL gate routing to ``End_Returned``. Time only ever advances via the
injected clock; firing is driven through the engine's ``fire_due(now)`` seam.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import MemorySaver

from amendia_bpmn import parse
from app.config import settings as app_settings
from app.dal.hitl_task_repo import HitlTaskRepository
from app.dal.instance_repo import ProcessInstanceRepository
from app.dal.timer_repo import TimerRepository
from app.db.mongo import HITL_TASKS, PROCESS_INSTANCES, TIMERS, create_indexes
from app.engine.bundle import PackBundle
from app.engine.compiler import compile_graph
from app.engine.engine import ProcessEngine
from app.engine.executor import InProcessExecutor
from amendia_contracts.hitl_task import TaskStatus
from app.models.process_instance import InstanceStatus, ProcessInstance
from app.models.timer import TimerStatus
from app.services.timer_service import TimerService
from tests._wire import make_envelope, role_user


def _utc(dt: datetime) -> datetime:
    """Normalize a datetime read back from mongomock (custom UTC tzinfo) for instant comparison."""
    return dt.replace(tzinfo=timezone.utc)

PK, PV = "wire-repair-standard", "1.0.0"
_T0 = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t=_T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t = self.t + timedelta(**kw)


class FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, doc, routing_key, message_id):
        self.events.append((routing_key, doc))


class _Settings:
    EXECUTION_PROFILE = "timers"
    SIMULATION_MODE = True
    SELF_BASE_URL = "http://rt"


def _seed_xml() -> str:
    return (Path(app_settings.SEED_DIR) / "wire-repair.bpmn").read_text()


def _intermediate_xml() -> str:
    """Insert a timer intermediate-catch (PT1H) between Enrich (autonomous) and Assess (gate)."""
    xml = _seed_xml()
    return xml.replace(
        '<bpmn:sequenceFlow id="Flow_Enrich_Assess" sourceRef="Task_EnrichPayment" targetRef="Task_AssessRepairability"/>',
        '<bpmn:intermediateCatchEvent id="Wait"><bpmn:timerEventDefinition>'
        '<bpmn:timeDuration>PT1H</bpmn:timeDuration></bpmn:timerEventDefinition></bpmn:intermediateCatchEvent>'
        '<bpmn:sequenceFlow id="Flow_Enrich_Wait" sourceRef="Task_EnrichPayment" targetRef="Wait"/>'
        '<bpmn:sequenceFlow id="Flow_Wait_Assess" sourceRef="Wait" targetRef="Task_AssessRepairability"/>')


def _boundary_xml() -> str:
    """Attach an interrupting SLA boundary (PT4H) to the Task_ApproveRepair gate → End_Returned."""
    xml = _seed_xml()
    return xml.replace(
        "</bpmn:process>",
        '<bpmn:boundaryEvent id="Sla" attachedToRef="Task_ApproveRepair" cancelActivity="true">'
        '<bpmn:timerEventDefinition><bpmn:timeDuration>PT4H</bpmn:timeDuration></bpmn:timerEventDefinition>'
        '</bpmn:boundaryEvent>'
        '<bpmn:sequenceFlow id="Flow_Sla_Esc" sourceRef="Sla" targetRef="End_Returned"/>'
        "</bpmn:process>")


def _bundle(xml: str) -> PackBundle:
    b = PackBundle.from_seed_dir(app_settings.SEED_DIR)
    model, findings = parse(xml, b.manifest.process.process_id, profile="timers")
    errs = [f.code for f in findings if f.severity == "error"]
    assert errs == [], errs
    b.bpmn_model = model
    b.bpmn_xml = xml
    return b


@pytest_asyncio.fixture
async def harness():
    from mongomock_motor import AsyncMongoMockClient
    db = AsyncMongoMockClient()["amendia_test"]
    await create_indexes(db)
    instances = ProcessInstanceRepository(db[PROCESS_INSTANCES])
    hitl = HitlTaskRepository(db[HITL_TASKS])
    timer_repo = TimerRepository(db[TIMERS])
    clock = Clock()
    timers = TimerService(timer_repo, now=clock)
    pub = FakePublisher()
    checkpointer = MemorySaver()

    def build_engine(bundle):
        eng = ProcessEngine(
            registry=None, instance_repo=instances, hitl_repo=hitl, publisher=pub,
            settings=_Settings(), executor=InProcessExecutor(), checkpointer=checkpointer,
            timer_service=timers,
        )
        graph = compile_graph(bundle, eng._executor, simulation=True,
                              checkpointer=checkpointer, profile="timers")
        eng._bundles[(PK, PV)] = bundle
        eng._graphs[(PK, PV)] = graph
        return eng

    return {"instances": instances, "hitl": hitl, "timers": timers, "timer_repo": timer_repo,
            "clock": clock, "pub": pub, "build_engine": build_engine, "checkpointer": checkpointer}


async def _start(engine, instances, pid, reason="AC01"):
    inst = ProcessInstance.new(process_instance_id=pid, exception_id=f"EXC-{pid}",
                               pack_key=PK, pack_version=PV)
    await instances.insert(inst)
    await engine.start(inst, make_envelope(reason, exception_id=f"EXC-{pid}"))


def _decide(task):
    return {"decision": "complete" if task.hitl_mode.value == "manual" else "approve",
            "decided_by": role_user(task.role)}


async def _advance_to_gate(engine, hitl, pid, target):
    """Resume open gates (approve/complete) until the open task sits at ``target``. Mirrors what
    hitl_service.decide does: mark the task decided (so it isn't re-picked) THEN resume the graph."""
    for _ in range(20):
        open_tasks = await hitl.list(process_instance_id=pid, status="open")
        assert open_tasks, f"no open task for {pid}"
        t = open_tasks[0]
        if t.element_id == target:
            return t
        dec = _decide(t)
        rec = {"decision": dec["decision"], "decided_by": dec["decided_by"],
               "decided_at": _T0.isoformat()}
        await hitl.transition_status(t.task_id, expected_status=TaskStatus.OPEN,
                                     new_status=TaskStatus.DECIDED, set_fields={"decision": rec})
        await engine.resume(pid, dec, interrupt_id=t.interrupt_id)
    raise AssertionError(f"never reached gate {target}")


def _rk_events(pub, needle):
    return [d for rk, d in pub.events if needle in rk]


# --------------------------------------------------------------------------- #
# Timer intermediate catch (2.2.c)
# --------------------------------------------------------------------------- #

async def test_intermediate_catch_parks_then_fires(harness):
    eng = harness["build_engine"](_bundle(_intermediate_xml()))
    instances, timers, clock = harness["instances"], harness["timers"], harness["clock"]
    pid = "pi-int1"
    await _start(eng, instances, pid)

    # parked on the timer, one pending timer at now+1h
    inst = await instances.get(pid)
    assert inst.status == InstanceStatus.WAITING_TIMER
    pend = await timers.list_for_instance(pid)
    assert len(pend) == 1 and pend[0].status == TimerStatus.PENDING
    assert _utc(pend[0].fire_at) == _T0 + timedelta(hours=1)

    # not due yet → poller no-ops, still parked
    assert await eng.fire_due() == 0
    assert (await instances.get(pid)).status == InstanceStatus.WAITING_TIMER

    # advance past fire_at → fires once, graph proceeds to the next (Assess) gate
    clock.advance(hours=1)
    assert await eng.fire_due() == 1
    assert (await instances.get(pid)).status == InstanceStatus.WAITING_HITL
    assert (await timers.list_for_instance(pid))[0].status == TimerStatus.FIRED
    nxt = (await harness["hitl"].list(process_instance_id=pid, status="open"))[0]
    assert nxt.element_id == "Task_AssessRepairability"


# --------------------------------------------------------------------------- #
# Interrupting SLA boundary on a HITL gate (2.2.d)
# --------------------------------------------------------------------------- #

async def test_boundary_timer_first_escalates_and_expires(harness):
    eng = harness["build_engine"](_bundle(_boundary_xml()))
    instances, hitl, timers, clock, pub = (
        harness["instances"], harness["hitl"], harness["timers"], harness["clock"], harness["pub"])
    pid = "pi-b1"
    await _start(eng, instances, pid)
    task = await _advance_to_gate(eng, hitl, pid, "Task_ApproveRepair")

    # a boundary timer was registered and the task carries the SLA due_at
    assert _utc(task.due_at) == _T0 + timedelta(hours=4)
    bt = [t for t in await timers.list_for_instance(pid) if t.kind.value == "boundary"]
    assert len(bt) == 1 and bt[0].status == TimerStatus.PENDING

    # SLA breach: fire the timer → task expired, routed to the escalation end, no approver commit
    clock.advance(hours=4, minutes=1)
    assert await eng.fire_due() == 1
    expired = await hitl.get(task.task_id)
    assert expired.status.value == "expired"
    inst = await instances.get(pid)
    assert inst.status == InstanceStatus.COMPLETED and inst.outcome == "End_Returned"
    assert _rk_events(pub, "hitl_task_expired")
    # the boundary timer resolved to fired; the escalation event names the diagram's target
    assert [t for t in await timers.list_for_instance(pid) if t.kind.value == "boundary"][0].status \
        == TimerStatus.FIRED
    exp_evt = _rk_events(pub, "hitl_task_expired")[0]
    assert exp_evt["escalated_to"] == "End_Returned"
    # actor_log at the gate records the timer as the actor — never an approving human
    cfg = {"configurable": {"thread_id": pid}}
    final = eng._graphs[(PK, PV)].get_state(cfg).values
    gate_log = [e for e in final["actor_log"] if e["element_id"] == "Task_ApproveRepair"]
    assert gate_log and all(e["kind"] == "timer" for e in gate_log)


async def test_boundary_late_human_decision_is_rejected(harness):
    # after the SLA expires the gate, a human can no longer claim/decide it (loser rejected).
    eng = harness["build_engine"](_bundle(_boundary_xml()))
    instances, hitl, clock = harness["instances"], harness["hitl"], harness["clock"]
    pid = "pi-b2"
    await _start(eng, instances, pid)
    task = await _advance_to_gate(eng, hitl, pid, "Task_ApproveRepair")
    clock.advance(hours=5)
    await eng.fire_due()

    from app.services.hitl_service import HitlDecisionService, HitlError
    svc = HitlDecisionService(hitl_repo=hitl, instance_repo=instances, engine=eng,
                              publisher=harness["pub"])
    with pytest.raises(HitlError) as ei:
        await svc.claim(task.task_id, actor_id="approver-1", actor_roles={task.role})
    assert ei.value.status_code == 409


async def test_boundary_human_first_cancels_timer(harness):
    eng = harness["build_engine"](_bundle(_boundary_xml()))
    instances, hitl, timers, clock = (
        harness["instances"], harness["hitl"], harness["timers"], harness["clock"])
    pid = "pi-b3"
    await _start(eng, instances, pid)
    task = await _advance_to_gate(eng, hitl, pid, "Task_ApproveRepair")

    # human decides BEFORE the SLA (mark decided as hitl_service would, then resume) → normal flow;
    # the boundary timer is cancelled.
    rec = {"decision": "complete", "decided_by": "approver-1", "decided_at": _T0.isoformat()}
    await hitl.transition_status(task.task_id, expected_status=TaskStatus.OPEN,
                                 new_status=TaskStatus.DECIDED, set_fields={"decision": rec})
    await eng.resume(pid, {"decision": "complete", "decided_by": "approver-1"},
                     interrupt_id=task.interrupt_id)
    bt = [t for t in await timers.list_for_instance(pid) if t.kind.value == "boundary"][0]
    assert bt.status == TimerStatus.CANCELLED
    # instance moved on to the next gate (SanctionsRescreen), NOT escalated
    nxt = await hitl.list(process_instance_id=pid, status="open")
    assert [t.element_id for t in nxt] == ["Task_SanctionsRescreen"]
    # a late timer tick is a no-op (cancelled timers are not due)
    clock.advance(hours=9)
    assert await eng.fire_due() == 0


# --------------------------------------------------------------------------- #
# Crash-safety (2.2.a)
# --------------------------------------------------------------------------- #

async def test_due_timer_fires_once_across_restart(harness):
    # engine1 parks the instance at the gate (registers the SLA timer) but never fires it.
    b = _bundle(_boundary_xml())
    eng1 = harness["build_engine"](b)
    instances, hitl, clock = harness["instances"], harness["hitl"], harness["clock"]
    pid = "pi-crash"
    await _start(eng1, instances, pid)
    await _advance_to_gate(eng1, hitl, pid, "Task_ApproveRepair")

    # "restart": a fresh engine sharing the durable checkpointer + repos + timers.
    eng2 = harness["build_engine"](b)
    clock.advance(hours=5)
    assert await eng2.fire_due() == 1              # the due pending timer fires once
    assert await eng2.fire_due() == 0              # ...and not again (idempotent — no double-escalation)
    inst = await instances.get(pid)
    assert inst.status == InstanceStatus.COMPLETED and inst.outcome == "End_Returned"
    assert len(_rk_events(harness["pub"], "hitl_task_expired")) == 1


# --------------------------------------------------------------------------- #
# Profile pin + load guard (2.2.e)
# --------------------------------------------------------------------------- #

def test_timer_pack_requires_timers_profile_to_compile():
    from app.engine.compiler import CompilerError
    b = _bundle(_boundary_xml())
    # under a lower profile the compilability gate refuses the timer construct
    with pytest.raises(CompilerError):
        compile_graph(b, InProcessExecutor(), simulation=True,
                      checkpointer=MemorySaver(), profile="common_subset")
    # under the timers profile it compiles
    compile_graph(b, InProcessExecutor(), simulation=True,
                  checkpointer=MemorySaver(), profile="timers")
