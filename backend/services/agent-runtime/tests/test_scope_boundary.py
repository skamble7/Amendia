# tests/test_scope_boundary.py
"""ADR-041 — interrupting boundaries on a subProcess (scope-level cancellation / error fallback).

Extends the ADR-040 single-node cancellation primitive to a whole scope. A **timer** boundary on a
subProcess self-enforces a scope-wide SLA (each inner node under the remaining scope budget; a breach by
any inner node diverts the whole scope, committing nothing). An **error** boundary on a subProcess is a
routing fallback — an inner node's unmatched modeled error routes to the enclosing scope's handler
(nested inner→outer). Deterministic: injected clock + hybrid/sim executors.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from amendia_bpmn import parse
from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.compiler import FAILED_OUTCOME, compile_graph
from app.engine.executor import InProcessExecutor
from app.engine.executor.base import CapabilityBusinessError
from app.engine.state import initial_state
from tests._wire import drive, make_envelope

SCOPE_SEED = str(settings.SEED_DIR).replace("wire-repair-standard", "scope-sla")
PID = "Process_ScopeSla"


def _jump_clock(after: float = 1e9):
    calls = {"n": 0}

    def now() -> float:
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else after
    return now


def _bundle(xml: str) -> PackBundle:
    b = PackBundle.from_seed_dir(SCOPE_SEED)
    model, findings = parse(xml, PID, profile="common_executable")
    assert [f.code for f in findings if f.severity == "error"] == [], [f.code for f in findings]
    b.bpmn_model = model
    b.bpmn_xml = xml
    return b


def _run(bundle, executor, *, tid, clock=None):
    app = compile_graph(bundle, executor, simulation=True, checkpointer=MemorySaver(),
                        profile="common_executable", clock=clock)
    return drive(app, {"configurable": {"thread_id": tid}},
                 initial_state(envelope=make_envelope("AC01"), trace={"correlation_id": "c"},
                               pack={"pack_key": "scope-sla", "pack_version": "1.0.0"}))[0]


# --------------------------------------------------------------------------- #
# Executors
# --------------------------------------------------------------------------- #
class _Block:
    """Sim everything except one capability, which blocks until cancelled (to breach the scope SLA)."""

    def __init__(self, cap):
        self._cap = cap
        self._fb = InProcessExecutor()

    def execute(self, d, i, ctx):
        if d.capability_id == self._cap:
            while not (ctx.cancel is not None and ctx.cancel.cancelled):
                time.sleep(0.002)
            return {"outputs": {"art.compose.val": {"n": 0, "tag": "x"}}}
        return self._fb.execute(d, i, ctx)


class _Raise:
    """Sim everything except one capability, which raises a modeled business error."""

    def __init__(self, cap, code):
        self._cap, self._code = cap, code
        self._fb = InProcessExecutor()

    def execute(self, d, i, ctx):
        if d.capability_id == self._cap:
            raise CapabilityBusinessError(self._code)
        return self._fb.execute(d, i, ctx)


# --------------------------------------------------------------------------- #
# BPMN builders (same task ids / process id as the seed so its bindings apply)
# --------------------------------------------------------------------------- #
_HDR = '<?xml version="1.0"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'


def _scope_bpmn(*, timer=False, scope_err=None, scope_catch_all=False, inner_err_on=None,
                inner_err_code=None, nested=False) -> str:
    """Build the scope process. Inner scope Sub_Timer{TaskA,TaskB,TaskC}. Optional timer/error boundary
    on the scope, an inner error boundary on a task, and a nested outer scope."""
    errdefs = ""
    boundaries = ""
    ends = '<bpmn:endEvent id="End_Done"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
    if timer:
        boundaries += ('<bpmn:boundaryEvent id="Sla" attachedToRef="Sub_Timer"><bpmn:timerEventDefinition>'
                       '<bpmn:timeDuration>PT2H</bpmn:timeDuration></bpmn:timerEventDefinition></bpmn:boundaryEvent>'
                       '<bpmn:sequenceFlow id="f_sla" sourceRef="Sla" targetRef="End_SLA"/>')
        ends += '<bpmn:endEvent id="End_SLA"><bpmn:incoming>f_sla</bpmn:incoming></bpmn:endEvent>'
    if scope_err or scope_catch_all:
        ref = ""
        if scope_err:
            errdefs += f'<bpmn:error id="ErrScope" errorCode="{scope_err}"/>'
            ref = ' errorRef="ErrScope"'
        boundaries += (f'<bpmn:boundaryEvent id="ErrBnd" attachedToRef="Sub_Timer"><bpmn:errorEventDefinition{ref}/>'
                       '</bpmn:boundaryEvent><bpmn:sequenceFlow id="f_err" sourceRef="ErrBnd" targetRef="End_Err"/>')
        ends += '<bpmn:endEvent id="End_Err"><bpmn:incoming>f_err</bpmn:incoming></bpmn:endEvent>'
    if inner_err_on:
        errdefs += f'<bpmn:error id="ErrInner" errorCode="{inner_err_code}"/>'
        boundaries += (f'<bpmn:boundaryEvent id="IErrBnd" attachedToRef="{inner_err_on}">'
                       '<bpmn:errorEventDefinition errorRef="ErrInner"/></bpmn:boundaryEvent>'
                       '<bpmn:sequenceFlow id="f_ierr" sourceRef="IErrBnd" targetRef="End_InnerErr"/>')
        ends += '<bpmn:endEvent id="End_InnerErr"><bpmn:incoming>f_ierr</bpmn:incoming></bpmn:endEvent>'

    inner = (
        '<bpmn:startEvent id="iS"><bpmn:outgoing>if1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="TaskA"><bpmn:incoming>if1</bpmn:incoming><bpmn:outgoing>if2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:serviceTask id="TaskB"><bpmn:incoming>if2</bpmn:incoming><bpmn:outgoing>if3</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:serviceTask id="TaskC"><bpmn:incoming>if3</bpmn:incoming><bpmn:outgoing>if4</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="iE"><bpmn:incoming>if4</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="if1" sourceRef="iS" targetRef="TaskA"/>'
        '<bpmn:sequenceFlow id="if2" sourceRef="TaskA" targetRef="TaskB"/>'
        '<bpmn:sequenceFlow id="if3" sourceRef="TaskB" targetRef="TaskC"/>'
        '<bpmn:sequenceFlow id="if4" sourceRef="TaskC" targetRef="iE"/>'
    )
    if nested:
        # Outer scope Sub_Outer wraps Sub_Timer; an outer error boundary catches OUTER_FAIL.
        errdefs += '<bpmn:error id="ErrOuter" errorCode="OUTER_FAIL"/>'
        boundaries += ('<bpmn:boundaryEvent id="OErrBnd" attachedToRef="Sub_Outer"><bpmn:errorEventDefinition errorRef="ErrOuter"/>'
                       '</bpmn:boundaryEvent><bpmn:sequenceFlow id="f_oerr" sourceRef="OErrBnd" targetRef="End_Outer"/>')
        ends += '<bpmn:endEvent id="End_Outer"><bpmn:incoming>f_oerr</bpmn:incoming></bpmn:endEvent>'
        body = (
            '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
            '<bpmn:subProcess id="Sub_Outer"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>'
            '<bpmn:startEvent id="oS"><bpmn:outgoing>of1</bpmn:outgoing></bpmn:startEvent>'
            f'<bpmn:subProcess id="Sub_Timer"><bpmn:incoming>of1</bpmn:incoming><bpmn:outgoing>of2</bpmn:outgoing>{inner}</bpmn:subProcess>'
            '<bpmn:endEvent id="oE"><bpmn:incoming>of2</bpmn:incoming></bpmn:endEvent>'
            '<bpmn:sequenceFlow id="of1" sourceRef="oS" targetRef="Sub_Timer"/>'
            '<bpmn:sequenceFlow id="of2" sourceRef="Sub_Timer" targetRef="oE"/>'
            '</bpmn:subProcess>'
            + ends +
            '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Sub_Outer"/>'
            '<bpmn:sequenceFlow id="f2" sourceRef="Sub_Outer" targetRef="End_Done"/>'
        )
    else:
        body = (
            '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
            f'<bpmn:subProcess id="Sub_Timer"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>{inner}</bpmn:subProcess>'
            + ends +
            '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Sub_Timer"/>'
            '<bpmn:sequenceFlow id="f2" sourceRef="Sub_Timer" targetRef="End_Done"/>'
        )
    return f'{_HDR}{errdefs}<bpmn:process id="{PID}" isExecutable="true">{body}{boundaries}</bpmn:process></bpmn:definitions>'


# =========================================================================== #
# Timer scope (the ADR-040 extension) — uses the seed file directly
# =========================================================================== #
def _seed_bundle() -> PackBundle:
    return PackBundle.from_seed_dir(SCOPE_SEED)


def test_scope_sla_within_deadline_completes():
    final = _run(_seed_bundle(), InProcessExecutor(), tid="within")
    assert final["outcome"] == "End_Done"
    assert set(final["artifacts"]) == {"a", "b", "c"}      # all three inner tasks ran
    assert "Sub_Timer" not in (final.get("boundary") or {})


def test_scope_sla_breach_diverts_and_skips_rest():
    final = _run(_seed_bundle(), _Block("cap.scope.sb"), tid="breach", clock=_jump_clock())
    assert final["boundary"]["Sub_Timer"] == {"kind": "timer"}
    assert final["outcome"] == "End_SLA"                    # routed to the scope timer target
    assert set(final["artifacts"]) == {"a"}                 # TaskA committed; TaskB breached; TaskC skipped
    assert any(e["element_id"] == "Sub_Timer" and e["kind"] == "timer" for e in final["actor_log"])


def test_scope_sla_reentrant_idempotent():
    b = _seed_bundle()
    a1 = _run(b, _Block("cap.scope.sb"), tid="re1", clock=_jump_clock())
    a2 = _run(b, _Block("cap.scope.sb"), tid="re2", clock=_jump_clock())
    assert a1["boundary"]["Sub_Timer"] == a2["boundary"]["Sub_Timer"] == {"kind": "timer"}
    assert set(a1["artifacts"]) == set(a2["artifacts"]) == {"a"}


# =========================================================================== #
# Error boundary on a scope (routing fallback)
# =========================================================================== #
def test_error_routes_to_scope_handler_by_code():
    b = _bundle(_scope_bpmn(scope_err="SCOPE_FAIL"))
    final = _run(b, _Raise("cap.scope.sb", "SCOPE_FAIL"), tid="err-code")
    assert final["outcome"] == "End_Err"
    assert final["boundary"]["TaskB"] == {"kind": "error", "code": "SCOPE_FAIL"}


def test_error_routes_to_scope_catch_all():
    b = _bundle(_scope_bpmn(scope_catch_all=True))
    final = _run(b, _Raise("cap.scope.sb", "ANYTHING"), tid="err-ca")
    assert final["outcome"] == "End_Err"


def test_inner_boundary_wins_over_scope():
    b = _bundle(_scope_bpmn(scope_err="SCOPE_FAIL", inner_err_on="TaskB", inner_err_code="SCOPE_FAIL"))
    final = _run(b, _Raise("cap.scope.sb", "SCOPE_FAIL"), tid="inner-wins")
    assert final["outcome"] == "End_InnerErr"               # the node's own boundary catches first


def test_error_no_match_anywhere_goes_to_failure_sink():
    b = _bundle(_scope_bpmn(scope_err="OTHER_CODE"))
    final = _run(b, _Raise("cap.scope.sb", "UNMATCHED"), tid="err-none")
    assert final["outcome"] == FAILED_OUTCOME


def test_nested_scope_inner_handler_wins():
    # both Sub_Timer (inner, catches SCOPE_FAIL) and Sub_Outer (catches OUTER_FAIL); an inner SCOPE_FAIL
    # is caught by the inner scope, not the outer.
    b = _bundle(_scope_bpmn(scope_err="SCOPE_FAIL", nested=True))
    final = _run(b, _Raise("cap.scope.sb", "SCOPE_FAIL"), tid="nested")
    assert final["outcome"] == "End_Err"                    # inner-most matching scope wins
