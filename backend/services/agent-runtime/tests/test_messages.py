# tests/test_messages.py
"""ADR-031 / Phase 2.4 — message catch / receive task / event-based gateway, end to end.

Drives the REAL ProcessEngine (+ mongomock, MemorySaver) over the seed BPMN transformed to add a
message construct, with a synthetic message binding injected into the in-memory bundle. Delivery is
driven directly via ``engine.deliver_message`` (no network) — deterministic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import MemorySaver

from amendia_bpmn import parse
from amendia_contracts.process_pack import ArtifactIO, Binding, MessageExecutor
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
from app.engine.compiler import compile_graph
from app.engine.engine import ProcessEngine
from app.engine.executor import InProcessExecutor
from app.models.process_instance import InstanceStatus, ProcessInstance
from app.services.message_service import MessageSubscriptionService
from app.services.timer_service import TimerService
from tests._wire import make_envelope

PK, PV = "wire-repair-standard", "1.0.0"
_T0 = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
_REPLY_SCHEMA = {"type": "object", "required": ["answer"], "additionalProperties": False,
                 "properties": {"answer": {"type": "string"}}}


class Clock:
    def __init__(self, t=_T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        from datetime import timedelta
        self.t = self.t + timedelta(**kw)


class FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, doc, rk, mid):
        self.events.append((rk, doc))


class _Settings:
    EXECUTION_PROFILE = "messages"
    SIMULATION_MODE = True
    SELF_BASE_URL = "http://rt"


def _seed_xml() -> str:
    return (Path(app_settings.SEED_DIR) / "wire-repair.bpmn").read_text()


def _catch_xml(kind="message") -> str:
    """Insert a message catch (or receive task) between Enrich (autonomous) and Assess."""
    node = ('<bpmn:intermediateCatchEvent id="AwaitReply"><bpmn:messageEventDefinition/></bpmn:intermediateCatchEvent>'
            if kind == "message" else '<bpmn:receiveTask id="AwaitReply"/>')
    return _seed_xml().replace(
        '<bpmn:sequenceFlow id="Flow_Enrich_Assess" sourceRef="Task_EnrichPayment" targetRef="Task_AssessRepairability"/>',
        node +
        '<bpmn:sequenceFlow id="Flow_Enrich_Await" sourceRef="Task_EnrichPayment" targetRef="AwaitReply"/>'
        '<bpmn:sequenceFlow id="Flow_Await_Assess" sourceRef="AwaitReply" targetRef="Task_AssessRepairability"/>')


def _event_gateway_xml() -> str:
    """Enrich → eventGateway → { message 'Result' → Assess | timer 'Timeout' → End_Returned }."""
    return _seed_xml().replace(
        '<bpmn:sequenceFlow id="Flow_Enrich_Assess" sourceRef="Task_EnrichPayment" targetRef="Task_AssessRepairability"/>',
        '<bpmn:eventBasedGateway id="Gw"/>'
        '<bpmn:intermediateCatchEvent id="Result"><bpmn:messageEventDefinition/></bpmn:intermediateCatchEvent>'
        '<bpmn:intermediateCatchEvent id="Timeout"><bpmn:timerEventDefinition><bpmn:timeDuration>PT2H</bpmn:timeDuration></bpmn:timerEventDefinition></bpmn:intermediateCatchEvent>'
        '<bpmn:sequenceFlow id="Flow_Enrich_Gw" sourceRef="Task_EnrichPayment" targetRef="Gw"/>'
        '<bpmn:sequenceFlow id="gm" sourceRef="Gw" targetRef="Result"/>'
        '<bpmn:sequenceFlow id="ga" sourceRef="Gw" targetRef="Timeout"/>'
        '<bpmn:sequenceFlow id="fm" sourceRef="Result" targetRef="Task_AssessRepairability"/>'
        '<bpmn:sequenceFlow id="ft" sourceRef="Timeout" targetRef="End_Returned"/>')


def _bundle(xml: str, message_bindings) -> PackBundle:
    """message_bindings: list of (element_id, element_kind, message_name, typed: bool)."""
    b = PackBundle.from_seed_dir(app_settings.SEED_DIR)
    model, findings = parse(xml, b.manifest.process.process_id, profile="messages")
    errs = [f.code for f in findings if f.severity == "error"]
    assert errs == [], errs
    b.bpmn_model = model
    b.bpmn_xml = xml
    for element_id, kind, name, typed in message_bindings:
        outputs = [ArtifactIO(name="reply", schema="art.test.reply@^1.0.0")] if typed else []
        b.manifest.bindings.append(Binding(
            element_id=element_id, element_kind=kind,
            executor=MessageExecutor(type="message", message_name=name), outputs=outputs))
        rb = {"element_id": element_id, "executor_capability": None, "assist_capability": None,
              "inputs": [], "outputs": ([{"name": "reply", "schema": "art.test.reply@1.0.0"}] if typed else [])}
        b.resolution["bindings"].append(rb)
        if typed:
            b.schemas["art.test.reply@1.0.0"] = _REPLY_SCHEMA
    return b


@pytest_asyncio.fixture
async def harness():
    from mongomock_motor import AsyncMongoMockClient
    db = AsyncMongoMockClient()["amendia_test"]
    await create_indexes(db)
    instances = ProcessInstanceRepository(db[PROCESS_INSTANCES])
    hitl = HitlTaskRepository(db[HITL_TASKS])
    clock = Clock()
    timers = TimerService(TimerRepository(db[TIMERS]), now=clock)
    messages = MessageSubscriptionService(
        MessageSubscriptionRepository(db[MESSAGE_SUBSCRIPTIONS]),
        PendingMessageRepository(db[PENDING_MESSAGES]))
    pub = FakePublisher()
    cp = MemorySaver()

    def build_engine(bundle):
        eng = ProcessEngine(registry=None, instance_repo=instances, hitl_repo=hitl, publisher=pub,
                            settings=_Settings(), executor=InProcessExecutor(), checkpointer=cp,
                            timer_service=timers, message_service=messages)
        eng._bundles[(PK, PV)] = bundle
        eng._graphs[(PK, PV)] = compile_graph(bundle, eng._executor, simulation=True,
                                              checkpointer=cp, profile="messages")
        return eng

    return {"instances": instances, "messages": messages, "timers": timers, "pub": pub,
            "build_engine": build_engine, "clock": clock}


async def _start(engine, instances, pid, reason="AC01"):
    inst = ProcessInstance.new(process_instance_id=pid, exception_id=f"EXC-{pid}",
                               pack_key=PK, pack_version=PV)
    await instances.insert(inst)
    await engine.start(inst, make_envelope(reason, exception_id=f"EXC-{pid}"))
    return inst


def _rk(pub, needle):
    return [d for rk, d in pub.events if needle in rk]


# --------------------------------------------------------------------------- #
# Message intermediate catch
# --------------------------------------------------------------------------- #

async def test_message_catch_parks_then_delivery_resumes(harness):
    eng = harness["build_engine"](_bundle(_catch_xml(), [("AwaitReply", "messageCatch", "rfi_reply", False)]))
    instances, messages, pub = harness["instances"], harness["messages"], harness["pub"]
    pid = "pi-m1"
    await _start(eng, instances, pid)
    assert (await instances.get(pid)).status == InstanceStatus.WAITING_MESSAGE
    subs = await messages.list_for_instance(pid)
    assert len(subs) == 1 and subs[0].message_name == "rfi_reply" and subs[0].status.value == "pending"

    res = await eng.deliver_message("rfi_reply", exception_id=f"EXC-{pid}", payload={"answer": "yes"})
    assert res["status"] == "delivered"
    # resumed past the catch → next gate (Assess); subscription consumed; event emitted; signal recorded
    assert (await instances.get(pid)).status == InstanceStatus.WAITING_HITL
    assert (await messages.list_for_instance(pid))[0].status.value == "consumed"
    assert _rk(pub, "message_received")


async def test_wrong_name_and_anchor_return_no_match(harness):
    eng = harness["build_engine"](_bundle(_catch_xml(), [("AwaitReply", "messageCatch", "rfi_reply", False)]))
    await _start(eng, harness["instances"], "pi-m2")
    assert (await eng.deliver_message("WRONG", exception_id="EXC-pi-m2"))["status"] == "no_matching_subscription"
    assert (await eng.deliver_message("rfi_reply", exception_id="EXC-none"))["status"] == "no_matching_subscription"


async def test_duplicate_delivery_is_already_consumed(harness):
    eng = harness["build_engine"](_bundle(_catch_xml(), [("AwaitReply", "messageCatch", "rfi_reply", False)]))
    await _start(eng, harness["instances"], "pi-m3")
    assert (await eng.deliver_message("rfi_reply", exception_id="EXC-pi-m3", payload={}))["status"] == "delivered"
    assert (await eng.deliver_message("rfi_reply", exception_id="EXC-pi-m3", payload={}))["status"] == "already_consumed"


# --------------------------------------------------------------------------- #
# Typed payload: validate + commit
# --------------------------------------------------------------------------- #

async def test_typed_payload_validates_and_commits(harness):
    eng = harness["build_engine"](_bundle(_catch_xml(), [("AwaitReply", "messageCatch", "rfi_reply", True)]))
    instances = harness["instances"]
    pid = "pi-m4"
    await _start(eng, instances, pid)
    res = await eng.deliver_message("rfi_reply", exception_id=f"EXC-{pid}", payload={"answer": "confirmed"})
    assert res["status"] == "delivered"
    cfg = {"configurable": {"thread_id": pid}}
    state = eng._graphs[(PK, PV)].get_state(cfg).values
    assert state["artifacts"]["reply"] == {"answer": "confirmed"}   # committed as the declared artifact


async def test_malformed_typed_payload_rejected_nothing_committed(harness):
    eng = harness["build_engine"](_bundle(_catch_xml(), [("AwaitReply", "messageCatch", "rfi_reply", True)]))
    instances = harness["instances"]
    pid = "pi-m5"
    await _start(eng, instances, pid)
    res = await eng.deliver_message("rfi_reply", exception_id=f"EXC-{pid}", payload={"wrong": 1})
    assert res["status"] == "invalid_payload"
    # instance stays parked; nothing committed
    assert (await instances.get(pid)).status == InstanceStatus.WAITING_MESSAGE
    state = eng._graphs[(PK, PV)].get_state({"configurable": {"thread_id": pid}}).values
    assert "reply" not in state.get("artifacts", {})


# --------------------------------------------------------------------------- #
# Ordering race + receive task + crash-safety
# --------------------------------------------------------------------------- #

async def test_message_arriving_before_subscription_is_buffered(harness):
    eng = harness["build_engine"](_bundle(_catch_xml(), [("AwaitReply", "messageCatch", "rfi_reply", False)]))
    instances = harness["instances"]
    pid = "pi-m6"
    # deliver BEFORE the instance starts/parks → buffered
    res = await eng.deliver_message("rfi_reply", exception_id=f"EXC-{pid}", payload={"answer": "early"})
    assert res["status"] == "no_matching_subscription"
    # now start: parking pops the buffer and delivers immediately → runs past the catch
    await _start(eng, instances, pid)
    assert (await instances.get(pid)).status == InstanceStatus.WAITING_HITL


async def test_receive_task_parks_and_resumes(harness):
    eng = harness["build_engine"](_bundle(_catch_xml("receive"), [("AwaitReply", "receiveTask", "rfi_reply", False)]))
    instances = harness["instances"]
    pid = "pi-m7"
    await _start(eng, instances, pid)
    assert (await instances.get(pid)).status == InstanceStatus.WAITING_MESSAGE
    assert (await eng.deliver_message("rfi_reply", exception_id=f"EXC-{pid}", payload={}))["status"] == "delivered"
    assert (await instances.get(pid)).status == InstanceStatus.WAITING_HITL


async def test_pending_subscription_survives_restart(harness):
    b = _bundle(_catch_xml(), [("AwaitReply", "messageCatch", "rfi_reply", False)])
    eng1 = harness["build_engine"](b)
    instances = harness["instances"]
    pid = "pi-m8"
    await _start(eng1, instances, pid)  # parked WAITING_MESSAGE, subscription pending
    # "restart": a fresh engine sharing the durable checkpointer + repos
    eng2 = harness["build_engine"](b)
    assert (await eng2.deliver_message("rfi_reply", exception_id=f"EXC-{pid}", payload={}))["status"] == "delivered"
    assert (await instances.get(pid)).status == InstanceStatus.WAITING_HITL


# --------------------------------------------------------------------------- #
# Event-based gateway (capstone)
# --------------------------------------------------------------------------- #

async def test_event_gateway_message_arm_wins_cancels_timer(harness):
    eng = harness["build_engine"](_bundle(_event_gateway_xml(), [("Result", "messageCatch", "screening_result", False)]))
    instances, timers, messages = harness["instances"], harness["timers"], harness["messages"]
    pid = "pi-eg1"
    await _start(eng, instances, pid)
    assert (await instances.get(pid)).status == InstanceStatus.WAITING_MESSAGE
    # both arms registered
    assert len(await messages.list_for_instance(pid)) == 1
    assert len(await timers.list_for_instance(pid)) == 1

    res = await eng.deliver_message("screening_result", exception_id=f"EXC-{pid}", payload={"hit": False})
    assert res["status"] == "delivered"
    # message arm won → routed to Assess (WAITING_HITL); the timer arm was cancelled
    assert (await instances.get(pid)).status == InstanceStatus.WAITING_HITL
    assert (await timers.list_for_instance(pid))[0].status.value == "cancelled"


async def test_event_gateway_timer_arm_wins_cancels_subscription(harness):
    eng = harness["build_engine"](_bundle(_event_gateway_xml(), [("Result", "messageCatch", "screening_result", False)]))
    instances, timers, messages = harness["instances"], harness["timers"], harness["messages"]
    clock = harness["clock"]
    pid = "pi-eg2"
    await _start(eng, instances, pid)
    clock.advance(hours=3)
    assert await eng.fire_due() == 1
    # timer arm won → routed to End_Returned (completed); the message subscription was cancelled
    inst = await instances.get(pid)
    assert inst.status == InstanceStatus.COMPLETED and inst.outcome == "End_Returned"
    assert (await messages.list_for_instance(pid))[0].status.value == "cancelled"
