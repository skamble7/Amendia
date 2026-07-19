# tests/test_event_subprocess.py
"""ADR-042 / Item F — event sub-process (triggeredByEvent="true"): a scope-wide interrupting handler.

Reuses the ADR-041 scope machinery (a boundary registered onto its enclosing scope), generalized so
the enclosing scope may be the **whole process** — which a subProcess boundary cannot express. An
**error** start makes the ESP a scope-wide error fallback (routed inner→outer, inner-most wins); a
**timer** start makes it a scope-wide SLA (a breach anywhere diverts to the handler, committing
nothing, re-entrant). The handler is the ESP body, inlined. Deterministic: injected clock + sim/hybrid
executors, no network.
"""
from __future__ import annotations

import time

import pytest
from langgraph.checkpoint.memory import MemorySaver

from amendia_bpmn import parse
from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.compiler import FAILED_OUTCOME, CompilerError, compile_graph
from app.engine.executor import InProcessExecutor
from app.engine.executor.base import CapabilityBusinessError
from app.engine.state import initial_state
from tests._wire import drive, make_envelope

SEED = str(settings.SEED_DIR).replace("wire-repair-standard", "event-handler")
PID = "Process_EventHandler"
_HDR = '<?xml version="1.0"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'


def _jump_clock(after: float = 1e9):
    calls = {"n": 0}

    def now() -> float:
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else after
    return now


class _Block:
    """Sim everything except one capability, which blocks until cancelled (to breach the scope SLA)."""

    def __init__(self, cap):
        self._cap, self._fb = cap, InProcessExecutor()

    def execute(self, d, i, ctx):
        if d.capability_id == self._cap:
            while not (ctx.cancel is not None and ctx.cancel.cancelled):
                time.sleep(0.002)
            return {"outputs": {"art.compose.val": {"n": 0, "tag": "x"}}}
        return self._fb.execute(d, i, ctx)


class _Raise:
    """Sim everything except one capability, which raises a modeled business error."""

    def __init__(self, cap, code):
        self._cap, self._code, self._fb = cap, code, InProcessExecutor()

    def execute(self, d, i, ctx):
        if d.capability_id == self._cap:
            raise CapabilityBusinessError(self._code)
        return self._fb.execute(d, i, ctx)


def _seed_bundle() -> PackBundle:
    return PackBundle.from_seed_dir(SEED)


def _bundle(xml: str) -> PackBundle:
    b = PackBundle.from_seed_dir(SEED)
    model, findings = parse(xml, PID, profile="common_executable")
    assert [f.code for f in findings if f.severity == "error"] == [], [f.code for f in findings]
    b.bpmn_model, b.bpmn_xml = model, xml
    return b


def _run(bundle, executor, *, tid, clock=None):
    app = compile_graph(bundle, executor, simulation=True, checkpointer=MemorySaver(),
                        profile="common_executable", clock=clock)
    return drive(app, {"configurable": {"thread_id": tid}},
                 initial_state(envelope=make_envelope("AC01"), trace={"correlation_id": "c"},
                               pack={"pack_key": "event-handler", "pack_version": "1.0.0"}))[0]


# --------------------------------------------------------------------------- #
# BPMN builders (Screen = main task, Handle = ESP body handler task — both bound by the seed)
# --------------------------------------------------------------------------- #
def _handle_body(esp_id, start_xml) -> str:
    return (f'<bpmn:subProcess id="{esp_id}" triggeredByEvent="true">{start_xml}'
            f'<bpmn:serviceTask id="Handle"><bpmn:incoming>{esp_id}_1</bpmn:incoming><bpmn:outgoing>{esp_id}_2</bpmn:outgoing></bpmn:serviceTask>'
            f'<bpmn:endEvent id="eEnd"><bpmn:incoming>{esp_id}_2</bpmn:incoming></bpmn:endEvent>'
            f'<bpmn:sequenceFlow id="{esp_id}_1" sourceRef="{esp_id}_S" targetRef="Handle"/>'
            f'<bpmn:sequenceFlow id="{esp_id}_2" sourceRef="Handle" targetRef="eEnd"/>'
            f'</bpmn:subProcess>')


def _empty_body(esp_id, start_xml, end_id) -> str:
    """An ESP whose body is start → end (a no-op handler that just routes to a distinct end)."""
    return (f'<bpmn:subProcess id="{esp_id}" triggeredByEvent="true">{start_xml}'
            f'<bpmn:endEvent id="{end_id}"><bpmn:incoming>{esp_id}_1</bpmn:incoming></bpmn:endEvent>'
            f'<bpmn:sequenceFlow id="{esp_id}_1" sourceRef="{esp_id}_S" targetRef="{end_id}"/>'
            f'</bpmn:subProcess>')


def _err_start(esp_id, ref=None):
    r = f' errorRef="{ref}"' if ref else ""
    return f'<bpmn:startEvent id="{esp_id}_S"><bpmn:errorEventDefinition{r}/><bpmn:outgoing>{esp_id}_1</bpmn:outgoing></bpmn:startEvent>'


def _proc(esp: str, *, defs="", main_extra="") -> str:
    """S → Screen → End_Done, plus the given event sub-process(es)."""
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="Screen"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="End_Done"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Screen"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Screen" targetRef="End_Done"/>'
        + esp + main_extra)
    return f'{_HDR}{defs}<bpmn:process id="{PID}" isExecutable="true">{inner}</bpmn:process></bpmn:definitions>'


# =========================================================================== #
# Timer event sub-process (a scope-wide SLA on the whole process)
# =========================================================================== #
def test_timer_esp_within_deadline_completes():
    # the seed's canonical process is a process-level timer ESP; within the deadline it never fires.
    final = _run(_seed_bundle(), InProcessExecutor(), tid="within")
    assert final["outcome"] == "End_Done"
    assert set(final["artifacts"]) == {"scr"}           # Screen ran; Handle (the ESP body) did not
    assert "Process_EventHandler" not in (final.get("boundary") or {})


def test_timer_esp_breach_runs_handler():
    final = _run(_seed_bundle(), _Block("cap.event.screen"), tid="breach", clock=_jump_clock())
    assert final["boundary"]["Process_EventHandler"] == {"kind": "timer"}   # process-wide SLA breached
    assert final["outcome"] == "eEnd"                   # routed into the ESP body (the handler)
    assert set(final["artifacts"]) == {"hnd"}           # Screen committed nothing; Handle ran
    assert any(e["element_id"] == "Process_EventHandler" and e["kind"] == "timer"
               for e in final["actor_log"])


def test_timer_esp_reentrant_idempotent():
    b = _seed_bundle()
    a1 = _run(b, _Block("cap.event.screen"), tid="re1", clock=_jump_clock())
    a2 = _run(b, _Block("cap.event.screen"), tid="re2", clock=_jump_clock())
    assert a1["boundary"]["Process_EventHandler"] == a2["boundary"]["Process_EventHandler"] == {"kind": "timer"}
    assert set(a1["artifacts"]) == set(a2["artifacts"]) == {"hnd"}
    assert a1["outcome"] == a2["outcome"] == "eEnd"


# =========================================================================== #
# Error event sub-process (a scope-wide error fallback)
# =========================================================================== #
def test_process_error_esp_by_code():
    xml = _proc(_handle_body("ESP", _err_start("ESP", "E")), defs='<bpmn:error id="E" errorCode="screening.hit"/>')
    final = _run(_bundle(xml), _Raise("cap.event.screen", "screening.hit"), tid="err-code")
    assert final["outcome"] == "eEnd"
    assert set(final["artifacts"]) == {"hnd"}
    assert final["boundary"]["Screen"] == {"kind": "error", "code": "screening.hit"}


def test_process_error_esp_catch_all():
    xml = _proc(_handle_body("ESP", _err_start("ESP")))          # no errorRef → catch-all
    final = _run(_bundle(xml), _Raise("cap.event.screen", "anything"), tid="err-ca")
    assert final["outcome"] == "eEnd" and set(final["artifacts"]) == {"hnd"}


def test_process_error_esp_no_match_goes_to_failure_sink():
    xml = _proc(_handle_body("ESP", _err_start("ESP", "E")), defs='<bpmn:error id="E" errorCode="only.this"/>')
    final = _run(_bundle(xml), _Raise("cap.event.screen", "other.code"), tid="err-none")
    assert final["outcome"] == FAILED_OUTCOME


# =========================================================================== #
# Subprocess-scoped ESP + inner-most-wins precedence
# =========================================================================== #
def _sub_proc(*, sub_extra="", proc_esp="", inner_bnd="", defs="", ends_extra="") -> str:
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:subProcess id="Sub"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>'
        '<bpmn:startEvent id="iS"><bpmn:outgoing>if1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="Screen"><bpmn:incoming>if1</bpmn:incoming><bpmn:outgoing>if2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="iE"><bpmn:incoming>if2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="if1" sourceRef="iS" targetRef="Screen"/>'
        '<bpmn:sequenceFlow id="if2" sourceRef="Screen" targetRef="iE"/>'
        + sub_extra +
        '</bpmn:subProcess>'
        '<bpmn:endEvent id="End_Done"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Sub"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Sub" targetRef="End_Done"/>'
        + inner_bnd + ends_extra + proc_esp)
    return f'{_HDR}{defs}<bpmn:process id="{PID}" isExecutable="true">{inner}</bpmn:process></bpmn:definitions>'


def test_subprocess_scoped_error_esp():
    # the ESP is declared INSIDE Sub → it is a Sub-scoped handler (an inner node's error routes to it).
    xml = _sub_proc(sub_extra=_handle_body("ESP", _err_start("ESP", "E")),
                    defs='<bpmn:error id="E" errorCode="scope.fail"/>')
    final = _run(_bundle(xml), _Raise("cap.event.screen", "scope.fail"), tid="sub-esp")
    assert final["outcome"] == "eEnd" and set(final["artifacts"]) == {"hnd"}


def test_inner_boundary_beats_subprocess_esp():
    # Screen has its OWN error boundary; it wins over the Sub-scoped ESP for the same code.
    inner_bnd = ('<bpmn:boundaryEvent id="IBnd" attachedToRef="Screen"><bpmn:errorEventDefinition errorRef="E"/>'
                 '</bpmn:boundaryEvent><bpmn:sequenceFlow id="fib" sourceRef="IBnd" targetRef="End_InnerBnd"/>')
    ends = '<bpmn:endEvent id="End_InnerBnd"><bpmn:incoming>fib</bpmn:incoming></bpmn:endEvent>'
    xml = _sub_proc(sub_extra=_handle_body("ESP", _err_start("ESP", "E")), inner_bnd=inner_bnd,
                    ends_extra=ends, defs='<bpmn:error id="E" errorCode="scope.fail"/>')
    final = _run(_bundle(xml), _Raise("cap.event.screen", "scope.fail"), tid="inner-wins")
    assert final["outcome"] == "End_InnerBnd"           # the node's own boundary catches first
    assert "hnd" not in final["artifacts"]              # the ESP handler never ran


def test_subprocess_esp_beats_process_esp():
    # a Sub-scoped ESP (→ Handle) and a process-level ESP (→ End_ProcESP), both catching the same code;
    # an inner error is caught by the inner-most scope (Sub), not the process.
    proc_esp = _empty_body("ESP_P", _err_start("ESP_P", "E"), "End_ProcESP")
    xml = _sub_proc(sub_extra=_handle_body("ESP_S", _err_start("ESP_S", "E")), proc_esp=proc_esp,
                    defs='<bpmn:error id="E" errorCode="scope.fail"/>')
    final = _run(_bundle(xml), _Raise("cap.event.screen", "scope.fail"), tid="sub-beats-proc")
    assert final["outcome"] == "eEnd"                   # the Sub-scoped handler (Handle → eEnd)
    assert set(final["artifacts"]) == {"hnd"}


def test_process_esp_is_last_resort():
    # no Sub-scoped handler → the same inner error falls through to the process-level ESP.
    xml = _proc(_handle_body("ESP", _err_start("ESP", "E")), defs='<bpmn:error id="E" errorCode="scope.fail"/>')
    final = _run(_bundle(xml), _Raise("cap.event.screen", "scope.fail"), tid="proc-last")
    assert final["outcome"] == "eEnd" and set(final["artifacts"]) == {"hnd"}


# =========================================================================== #
# Refusals (the compiler refuses off the shared compilability gate)
# =========================================================================== #
def test_message_triggered_esp_refused_at_compile():
    start = '<bpmn:startEvent id="ESP_S"><bpmn:messageEventDefinition/><bpmn:outgoing>ESP_1</bpmn:outgoing></bpmn:startEvent>'
    xml = _proc(_handle_body("ESP", start))
    b = _bundle(xml)
    with pytest.raises(CompilerError, match="event sub-process"):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                      profile="common_executable")


def test_non_interrupting_esp_refused_at_compile():
    start = ('<bpmn:startEvent id="ESP_S" isInterrupting="false"><bpmn:errorEventDefinition/>'
             '<bpmn:outgoing>ESP_1</bpmn:outgoing></bpmn:startEvent>')
    xml = _proc(_handle_body("ESP", start))
    b = _bundle(xml)
    with pytest.raises(CompilerError, match="event sub-process"):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                      profile="common_executable")


def test_two_timer_esps_on_process_ambiguous_at_compile():
    def timer_start(esp_id):
        return (f'<bpmn:startEvent id="{esp_id}_S"><bpmn:timerEventDefinition><bpmn:timeDuration>PT2H</bpmn:timeDuration>'
                f'</bpmn:timerEventDefinition><bpmn:outgoing>{esp_id}_1</bpmn:outgoing></bpmn:startEvent>')
    esp1 = _empty_body("ESP1", timer_start("ESP1"), "e1")
    esp2 = _empty_body("ESP2", timer_start("ESP2"), "e2")
    xml = _proc(esp1 + esp2)
    b = _bundle(xml)
    with pytest.raises(CompilerError):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                      profile="common_executable")
