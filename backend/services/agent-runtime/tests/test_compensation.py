# tests/test_compensation.py
"""ADR-043 / Item G — compensation (explicit compensate-throw + reverse-order undo).

A compensable side-effectful activity logs a ``compensation_log`` entry on commit; a compensate-throw
event drives a **reverse (LIFO) order** undo, running each activity's bound handler through its HITL gate.
The driver marks each activity ``compensations_done`` as its undo commits, so a re-run (every HITL-resume
replays the driver node) undoes each activity **exactly once**. Deterministic: sim executor, drive()
auto-approves gates, no network.
"""
from __future__ import annotations

from collections import Counter

import pytest
from langgraph.checkpoint.memory import MemorySaver

from amendia_bpmn import parse
from app.config import settings
from app.engine.compensation import pending_compensations
from app.engine.compiler import CompilerError, compile_graph
from app.engine.executor import InProcessExecutor
from app.engine.state import initial_state
from app.engine.task_runner import NodeExecutionError
from tests._wire import drive, make_envelope

SEED = str(settings.SEED_DIR).replace("wire-repair-standard", "payment-compensation")
PID = "Process_PaymentComp"
_HDR = '<?xml version="1.0"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'

# The off-flow compensation handlers + boundaries + associations — present in every variant (the seed
# manifest binds Release/Debit/ReverseRelease/ReverseDebit).
_HANDLERS = (
    '<bpmn:boundaryEvent id="RelCompBnd" attachedToRef="Release"><bpmn:compensateEventDefinition/></bpmn:boundaryEvent>'
    '<bpmn:serviceTask id="ReverseRelease" isForCompensation="true"></bpmn:serviceTask>'
    '<bpmn:association id="a1" sourceRef="RelCompBnd" targetRef="ReverseRelease"/>'
    '<bpmn:boundaryEvent id="DbtCompBnd" attachedToRef="Debit"><bpmn:compensateEventDefinition/></bpmn:boundaryEvent>'
    '<bpmn:serviceTask id="ReverseDebit" isForCompensation="true"></bpmn:serviceTask>'
    '<bpmn:association id="a2" sourceRef="DbtCompBnd" targetRef="ReverseDebit"/>')


def _proc(spine: str) -> str:
    return f'{_HDR}<bpmn:process id="{PID}" isExecutable="true">{spine}{_HANDLERS}</bpmn:process></bpmn:definitions>'


def _seed_bundle():
    from app.engine.bundle import PackBundle
    return PackBundle.from_seed_dir(SEED)


def _bundle(xml: str):
    from app.engine.bundle import PackBundle
    b = PackBundle.from_seed_dir(SEED)
    model, findings = parse(xml, PID, profile="common_executable")
    assert [f.code for f in findings if f.severity == "error"] == [], [f.code for f in findings]
    b.bpmn_model, b.bpmn_xml = model, xml
    return b


def _run(bundle, *, tid, decide=None):
    app = compile_graph(bundle, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                        profile="common_executable")
    return drive(app, {"configurable": {"thread_id": tid}},
                 initial_state(envelope=make_envelope("AC01"), trace={"correlation_id": "c"},
                               pack={"pack_key": "payment-compensation", "pack_version": "1.0.0"}),
                 decide=decide)


def _undo_execs(final):
    """The undo CAPABILITY executions (kind=capability) — one per actual undo (not the human approval)."""
    return [e["element_id"] for e in final["actor_log"]
            if e.get("kind") == "capability" and e["element_id"] in ("ReverseRelease", "ReverseDebit")]


# --- happy path: no compensation -----------------------------------------------------------------

def test_happy_path_logs_but_does_not_compensate():
    # the seed's canonical process is linear (Release → Debit → End_Done); the throw is never reached.
    final, _ = _run(_seed_bundle(), tid="happy")
    assert final["outcome"] == "End_Done"
    assert set(final["artifacts"]) == {"rel", "dbt"}                     # both side effects stand
    # both compensable activities logged (completion order), but none undone
    assert [e["activity_id"] for e in final["compensation_log"]] == ["Release", "Debit"]
    assert final.get("compensations_done", {}) == {}
    assert _undo_execs(final) == []


# --- failure path: reverse-order undo ------------------------------------------------------------

_FAIL_SPINE = (
    '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
    '<bpmn:serviceTask id="Release"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
    '<bpmn:serviceTask id="Debit"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:serviceTask>'
    '<bpmn:endEvent id="CompThrow"><bpmn:incoming>f3</bpmn:incoming><bpmn:compensateEventDefinition/></bpmn:endEvent>'
    '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Release"/>'
    '<bpmn:sequenceFlow id="f2" sourceRef="Release" targetRef="Debit"/>'
    '<bpmn:sequenceFlow id="f3" sourceRef="Debit" targetRef="CompThrow"/>')


def test_failure_path_reverse_order_undo():
    final, gates = _run(_bundle(_proc(_FAIL_SPINE)), tid="fail")
    assert final["outcome"] == "CompThrow"                              # terminal compensate-throw end
    # Debit committed AFTER Release → its undo runs FIRST (LIFO)
    assert _undo_execs(final) == ["ReverseDebit", "ReverseRelease"]
    assert final["compensations_done"] == {"Debit": True, "Release": True}
    # the primaries logged once each; the undo handlers are NOT themselves compensable (no extra log)
    assert [e["activity_id"] for e in final["compensation_log"]] == ["Release", "Debit"]
    # every undo ran behind its HITL gate (compensation pauses for approval, per handler)
    assert [g["element_id"] for g in gates] == ["Release", "Debit", "ReverseDebit", "ReverseRelease"]


def test_no_double_undo_each_handler_runs_exactly_once():
    # drive() replays the driver node on every gate resume; if the driver weren't idempotent an undo
    # would execute twice. Each undo capability must appear exactly once.
    final, _ = _run(_bundle(_proc(_FAIL_SPINE)), tid="once")
    assert Counter(_undo_execs(final)) == Counter({"ReverseDebit": 1, "ReverseRelease": 1})
    # and nothing remains pending — a re-driven throw would be a no-op
    assert pending_compensations(final, PID, PID) == []


def test_pending_compensations_is_idempotent_over_done():
    log = [{"activity_id": "A", "handler_id": "hA", "scope": PID},
           {"activity_id": "B", "handler_id": "hB", "scope": PID}]
    # nothing done → LIFO order B, A
    assert [e["activity_id"] for e in pending_compensations({"compensation_log": log}, PID, PID)] == ["B", "A"]
    # B done → only A remains
    st = {"compensation_log": log, "compensations_done": {"B": True}}
    assert [e["activity_id"] for e in pending_compensations(st, PID, PID)] == ["A"]
    # all done → empty (a re-run never re-undoes)
    st2 = {"compensation_log": log, "compensations_done": {"A": True, "B": True}}
    assert pending_compensations(st2, PID, PID) == []
    # a duplicate log entry for A (idempotent re-commit) is undone once
    dup = {"compensation_log": log + [{"activity_id": "A", "handler_id": "hA", "scope": PID}]}
    got = [e["activity_id"] for e in pending_compensations(dup, PID, PID)]
    assert got == ["A", "B"]  # A appears once despite the duplicate


# --- empty scope: no-op ---------------------------------------------------------------------------

def test_compensate_throw_before_any_side_effect_is_noop():
    # the throw is reached BEFORE any compensable activity commits → nothing to undo → proceeds.
    spine = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:intermediateThrowEvent id="CompThrow"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>'
        '<bpmn:compensateEventDefinition/></bpmn:intermediateThrowEvent>'
        '<bpmn:serviceTask id="Release"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:serviceTask id="Debit"><bpmn:incoming>f3</bpmn:incoming><bpmn:outgoing>f4</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="End_Done"><bpmn:incoming>f4</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="CompThrow"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="CompThrow" targetRef="Release"/>'
        '<bpmn:sequenceFlow id="f3" sourceRef="Release" targetRef="Debit"/>'
        '<bpmn:sequenceFlow id="f4" sourceRef="Debit" targetRef="End_Done"/>')
    final, _ = _run(_bundle(_proc(spine)), tid="noop")
    assert final["outcome"] == "End_Done"                               # throw no-op'd, flow continued
    assert _undo_execs(final) == []
    assert final.get("compensations_done", {}) == {}


# --- HITL reject during compensation --------------------------------------------------------------

def test_reject_during_compensation_halts():
    # a rejected undo has no rejection route → the driver fails the instance (documented behavior).
    def reject_reverse(payload):
        if payload["element_id"] in ("ReverseDebit", "ReverseRelease"):
            return {"decision": "reject", "decided_by": "approver-1"}
        return {"decision": "approve", "decided_by": "approver-1"}
    with pytest.raises(NodeExecutionError):
        _run(_bundle(_proc(_FAIL_SPINE)), tid="reject", decide=reject_reverse)


# --- refusals (compiled off the shared gate) ------------------------------------------------------

def test_targeted_compensation_refused_at_compile():
    spine = _FAIL_SPINE.replace('<bpmn:compensateEventDefinition/>',
                                '<bpmn:compensateEventDefinition activityRef="Release"/>')
    b = _bundle(_proc(spine))
    with pytest.raises(CompilerError, match="targeted"):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                      profile="common_executable")


def test_transaction_cancel_refused_at_compile():
    # a cancel end event (transaction auto-compensation trigger) alongside a compensate throw → refused.
    spine2 = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="Release"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:serviceTask id="Debit"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="Cancel"><bpmn:incoming>f3</bpmn:incoming><bpmn:cancelEventDefinition/><bpmn:compensateEventDefinition/></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Release"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Release" targetRef="Debit"/>'
        '<bpmn:sequenceFlow id="f3" sourceRef="Debit" targetRef="Cancel"/>')
    b = _bundle(_proc(spine2))
    with pytest.raises(CompilerError, match="transaction"):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                      profile="common_executable")
