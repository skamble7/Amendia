# tests/test_error_boundary.py
"""ADR-030 / Phase 2.3 — error boundary events: a MODELED business error routes to the boundary
flow (instance stays running); technical failures still fail. Drives the seed BPMN transformed to
attach an error boundary to the ``Task_ApplyRepair`` serviceTask, whose sim capability raises
``CapabilityBusinessError("PAYMENT_REJECTED")`` under an ``RJCT`` steer.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
from app.engine.compiler import FAILED_OUTCOME, compile_graph
from app.engine.executor import InProcessExecutor
from app.engine.state import initial_state
from app.models.process_instance import InstanceStatus, ProcessInstance
from amendia_contracts.hitl_task import TaskStatus
from tests._wire import drive, make_envelope, role_user

PK, PV = "wire-repair-standard", "1.0.0"


def _seed_xml() -> str:
    return (Path(app_settings.SEED_DIR) / "wire-repair.bpmn").read_text()


def _error_xml(*, code="PAYMENT_REJECTED", target="End_Returned", catch_all=False) -> str:
    """Attach an error boundary to Task_ApplyRepair → `target`. Optionally a catch-all with a
    non-matching coded boundary, to exercise catch-all vs unmatched routing."""
    xml = _seed_xml()
    errdef = f'<bpmn:error id="Err" errorCode="{code}"/>'
    boundary = (
        '<bpmn:boundaryEvent id="BndRej" attachedToRef="Task_ApplyRepair">'
        '<bpmn:errorEventDefinition errorRef="Err"/></bpmn:boundaryEvent>'
        f'<bpmn:sequenceFlow id="Flow_Rej" sourceRef="BndRej" targetRef="{target}"/>'
    )
    if catch_all:
        boundary += (
            '<bpmn:boundaryEvent id="BndAny" attachedToRef="Task_ApplyRepair">'
            '<bpmn:errorEventDefinition/></bpmn:boundaryEvent>'
            f'<bpmn:sequenceFlow id="Flow_Any" sourceRef="BndAny" targetRef="{target}"/>'
        )
    xml = xml.replace("</bpmn:process>", boundary + "</bpmn:process>")
    # bpmn:error lives at the definitions level (sibling of process)
    xml = xml.replace("</bpmn:definitions>", errdef + "</bpmn:definitions>")
    return xml


def _bundle(xml: str) -> PackBundle:
    b = PackBundle.from_seed_dir(app_settings.SEED_DIR)
    model, findings = parse(xml, b.manifest.process.process_id, profile="error_boundary")
    errs = [f.code for f in findings if f.severity == "error"]
    assert errs == [], errs
    b.bpmn_model = model
    b.bpmn_xml = xml
    return b


def _graph(xml: str, profile="error_boundary"):
    return compile_graph(_bundle(xml), InProcessExecutor(), simulation=True,
                         checkpointer=MemorySaver(), profile=profile)


def _initial(reason_codes):
    env = make_envelope("AC01")
    env["reason_codes"] = reason_codes  # AC01 → repairable path; RJCT/TECHFAIL steer apply_repair
    return initial_state(envelope=env, trace={"correlation_id": "c"},
                         pack={"pack_key": PK, "pack_version": PV})


# --------------------------------------------------------------------------- #
# Graph-level routing (compiler + node)
# --------------------------------------------------------------------------- #

def test_business_error_routes_to_error_boundary_not_failure():
    app = _graph(_error_xml(target="End_Returned"))
    cfg = {"configurable": {"thread_id": "eb1"}}
    result, gates = drive(app, cfg, _initial(["AC01", "RJCT"]))
    # routed through the error boundary to its target end — NOT a failure
    assert result["outcome"] == "End_Returned"
    assert result["outcome"] != FAILED_OUTCOME
    assert result["boundary"]["Task_ApplyRepair"] == {"kind": "error", "code": "PAYMENT_REJECTED"}
    # actor_log records the capability + the business error code
    entry = next(e for e in result["actor_log"] if e["element_id"] == "Task_ApplyRepair"
                 and e.get("exec_meta", {}).get("business_error"))
    assert entry["exec_meta"]["business_error"] == "PAYMENT_REJECTED"


def test_catch_all_catches_a_code_with_no_specific_boundary():
    # only a catch-all boundary (coded one is for a different code) → PAYMENT_REJECTED still caught.
    app = _graph(_error_xml(code="SOMETHING_ELSE", target="End_Returned", catch_all=True))
    cfg = {"configurable": {"thread_id": "eb2"}}
    result, _ = drive(app, cfg, _initial(["AC01", "RJCT"]))
    assert result["outcome"] == "End_Returned" and result["outcome"] != FAILED_OUTCOME


def test_unmatched_code_no_catch_all_goes_to_failure_sink():
    # boundary catches a different code, no catch-all → PAYMENT_REJECTED is unmodeled → FAILURE_SINK.
    app = _graph(_error_xml(code="SOMETHING_ELSE", target="End_Returned", catch_all=False))
    cfg = {"configurable": {"thread_id": "eb3"}}
    result, _ = drive(app, cfg, _initial(["AC01", "RJCT"]))
    assert result["outcome"] == FAILED_OUTCOME
    assert "PAYMENT_REJECTED" in (result.get("last_error") or "")


def test_technical_failure_is_not_caught_by_error_boundary():
    # a plain exception (technical) must NOT be routed to the error boundary — it propagates/fails.
    app = _graph(_error_xml(target="End_Returned"))
    cfg = {"configurable": {"thread_id": "eb4"}}
    with pytest.raises(Exception):
        drive(app, cfg, _initial(["AC01", "TECHFAIL"]))


def test_no_business_error_takes_the_normal_flow():
    # without the steer, ApplyRepair succeeds and the normal path completes (End_Resolved).
    app = _graph(_error_xml(target="End_Returned"))
    cfg = {"configurable": {"thread_id": "eb5"}}
    result, _ = drive(app, cfg, _initial(["AC01"]))
    assert result["outcome"] == "End_Resolved"
    assert "Task_ApplyRepair" not in (result.get("boundary") or {})


def test_error_boundary_pack_refused_under_lower_profile():
    from app.engine.compiler import CompilerError
    with pytest.raises(CompilerError):
        _graph(_error_xml(), profile="common_subset")


# --------------------------------------------------------------------------- #
# Engine-level: instance stays running (no process_failed) through the boundary
# --------------------------------------------------------------------------- #

class _Settings:
    EXECUTION_PROFILE = "error_boundary"
    SIMULATION_MODE = True
    SELF_BASE_URL = "http://rt"


class FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, doc, routing_key, message_id):
        self.events.append((routing_key, doc))


@pytest_asyncio.fixture
async def engine_ctx():
    from mongomock_motor import AsyncMongoMockClient
    from app.engine.engine import ProcessEngine
    db = AsyncMongoMockClient()["amendia_test"]
    await create_indexes(db)
    instances = ProcessInstanceRepository(db[PROCESS_INSTANCES])
    hitl = HitlTaskRepository(db[HITL_TASKS])
    pub = FakePublisher()
    cp = MemorySaver()
    b = _bundle(_error_xml(target="End_Returned"))
    eng = ProcessEngine(registry=None, instance_repo=instances, hitl_repo=hitl, publisher=pub,
                        settings=_Settings(), executor=InProcessExecutor(), checkpointer=cp)
    eng._bundles[(PK, PV)] = b
    eng._graphs[(PK, PV)] = compile_graph(b, eng._executor, simulation=True,
                                          checkpointer=cp, profile="error_boundary")
    return {"eng": eng, "instances": instances, "hitl": hitl, "pub": pub}


async def _decide_all_gates(eng, hitl, pid):
    """Approve every gate the instance parks at until it terminates."""
    for _ in range(12):
        inst = await eng._instances.get(pid)
        if inst.status in (InstanceStatus.COMPLETED, InstanceStatus.FAILED):
            return inst
        t = (await hitl.list(process_instance_id=pid, status="open"))[0]
        dec = {"decision": "complete" if t.hitl_mode.value == "manual" else "approve",
               "decided_by": role_user(t.role)}
        await hitl.transition_status(t.task_id, expected_status=TaskStatus.OPEN,
                                     new_status=TaskStatus.DECIDED, set_fields={"decision": {**dec, "decided_at": "2026-07-17T12:00:00+00:00"}})
        await eng.resume(pid, dec, interrupt_id=t.interrupt_id)
    raise AssertionError("instance did not terminate")


async def test_engine_business_error_completes_not_failed(engine_ctx):
    eng, instances, pub = engine_ctx["eng"], engine_ctx["instances"], engine_ctx["pub"]
    inst = ProcessInstance.new(process_instance_id="pi-eb", exception_id="E-eb",
                               pack_key=PK, pack_version=PV)
    await instances.insert(inst)
    env = make_envelope("AC01"); env["reason_codes"] = ["AC01", "RJCT"]
    await eng.start(inst, env)
    final = await _decide_all_gates(eng, engine_ctx["hitl"], "pi-eb")
    # the modeled business error routed to End_Returned — completed, NOT failed
    assert final.status == InstanceStatus.COMPLETED and final.outcome == "End_Returned"
    assert not [rk for rk, _ in pub.events if "process_failed" in rk]
    assert [rk for rk, _ in pub.events if "process_completed" in rk]
