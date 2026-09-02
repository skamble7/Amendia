# tests/test_side_effect_waiver_runtime.py
"""ADR-065 P2 — runtime enforcement of the side-effect gate.

Until P1, an ungated side-effectful binding was an impossible manifest state, so the registry's activate
endpoint was a sufficient single chokepoint. P1 made "side-effectful at hitl 'none' with a justified waiver" a
LEGAL state — so the runtime must now tell a legitimately-waived binding from a mis-built / hand-edited manifest.

These prove: a side-effectful capability at 'none' with NO waiver fails closed BEFORE the tool is ever called
(D2); the same on the human-assist path that runs before the gate (D3); a catch-all error boundary cannot swallow
that failure (D4 — the wire-screen lesson); and a side-effectful multi-instance host is refused at compile (D5).
The seed packs are unaffected — every side-effectful seed cap is gated at approve_actions.
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver

from amendia_bpmn import parse
from amendia_contracts.capability import SideEffect
from amendia_contracts.process_pack import SideEffectWaiver
from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.compiler import CompilerError, compile_graph
from app.engine.state import initial_state
from app.engine.task_runner import NodeContext, NodeExecutionError, OutputSpec, make_task_node
from tests._stub_stack import stub_executor
from tests._wire import drive, make_envelope

_JUSTIFICATION = "Idempotent handback to the orchestrator; a re-run is a no-op, nothing for a human to gate."


class _Spy:
    """Records whether the tool (executor.execute) was ever called — the 'tool never called' assertion."""

    def __init__(self):
        self.calls = 0

    def execute(self, descriptor, inputs, ctx):
        self.calls += 1
        return {"outputs": {"art.x": {"ok": True}}, "log": "ran"}


def _descriptor(side_effect: str):
    return SimpleNamespace(capability_id="cap.payment.notify", kind=SimpleNamespace(value="skill"),
                           side_effect=SimpleNamespace(value=side_effect), constraints=None, idempotent=False)


def _cap_ctx(*, side_effect="side_effectful", hitl="none", waiver=None) -> NodeContext:
    return NodeContext(
        element_id="Task_X", element_kind="serviceTask", hitl_mode=hitl, role=None,
        executor_type="capability", descriptor=_descriptor(side_effect),
        outputs=[OutputSpec(name="out", artifact_key="art.x", schema_ref="art.x@1.0.0",
                            json_schema={"type": "object"})],
        side_effect_waiver=waiver)


def _human_ctx(*, assist_side_effect="side_effectful", hitl="none", waiver=None) -> NodeContext:
    return NodeContext(
        element_id="Task_H", element_kind="userTask", hitl_mode=hitl, role="role.payment.ops",
        executor_type="human", descriptor=None, assist_descriptor=_descriptor(assist_side_effect),
        outputs=[OutputSpec(name="out", artifact_key="art.x", schema_ref="art.x@1.0.0",
                            json_schema={"type": "object"})],
        side_effect_waiver=waiver)


def _run(ctx, executor):
    node = make_task_node(ctx, executor, simulation=False)
    return node({"envelope": {}, "artifacts": {}}, {"configurable": {"thread_id": "t"}})


# --------------------------------------------------------------------------- #
# D2 — the capability path
# --------------------------------------------------------------------------- #
def test_side_effectful_none_no_waiver_fails_closed_tool_never_called():
    spy = _Spy()
    with pytest.raises(NodeExecutionError) as ei:
        _run(_cap_ctx(waiver=None), spy)
    assert ei.value.reason == "side_effect_ungated"
    assert spy.calls == 0                              # the tool was NEVER called


def test_side_effectful_none_with_waiver_executes_and_logs(caplog):
    caplog.set_level(logging.INFO, logger="app.engine.task_runner")
    spy = _Spy()
    out = _run(_cap_ctx(waiver=SideEffectWaiver(justification=_JUSTIFICATION)), spy)
    assert spy.calls == 1                              # ran normally under the waiver
    assert out["artifacts"] == {"out": {"ok": True}}
    # an ungated real-world action is never silent — the justification is in the runtime log
    assert any("Idempotent handback" in r.getMessage() for r in caplog.records)


def test_read_only_none_is_unaffected():
    # the check keys on side_effect, not kind — a read_only capability at 'none' runs exactly as before.
    spy = _Spy()
    out = _run(_cap_ctx(side_effect="read_only", waiver=None), spy)
    assert spy.calls == 1 and out["artifacts"] == {"out": {"ok": True}}


# --------------------------------------------------------------------------- #
# D3 — the human-assist path (assist runs in mode="execute" BEFORE the gate)
# --------------------------------------------------------------------------- #
def test_assist_side_effectful_ungated_no_waiver_fails_closed_tool_never_called():
    spy = _Spy()
    with pytest.raises(NodeExecutionError) as ei:
        _run(_human_ctx(waiver=None), spy)
    assert ei.value.reason == "side_effect_ungated"
    assert spy.calls == 0                              # the assist tool was NEVER called


def test_assist_side_effectful_ungated_with_waiver_runs_assist(caplog):
    caplog.set_level(logging.INFO, logger="app.engine.task_runner")
    spy = _Spy()
    # the assist runs (spy called), THEN _run_manual reaches interrupt() — which raises RuntimeError at raw
    # node level (no checkpointer). That the assist ran at all proves the waiver let it past the check.
    with pytest.raises(RuntimeError):
        _run(_human_ctx(waiver=SideEffectWaiver(justification=_JUSTIFICATION)), spy)
    assert spy.calls == 1
    assert any("Idempotent handback" in r.getMessage() for r in caplog.records)


def test_assist_side_effectful_at_manual_still_requires_waiver_tool_never_called():
    # ADR-065 Part G (amended 2026-09-01): the assist runs BEFORE the interrupt, so 'manual' — the normal mode
    # for a human executor — does NOT cover it. A side-effectful assist at manual with no waiver still fails
    # closed; the tool is never called. (Corrects the pre-amendment assumption that a rank-2 gate exempted it.)
    spy = _Spy()
    with pytest.raises(NodeExecutionError) as ei:
        _run(_human_ctx(hitl="manual", waiver=None), spy)
    assert ei.value.reason == "side_effect_ungated"
    assert spy.calls == 0                              # the assist tool was NEVER called


def test_assist_side_effectful_at_manual_with_waiver_runs(caplog):
    caplog.set_level(logging.INFO, logger="app.engine.task_runner")
    spy = _Spy()
    with pytest.raises(RuntimeError):                  # the assist runs, then _run_manual reaches interrupt()
        _run(_human_ctx(hitl="manual", waiver=SideEffectWaiver(justification=_JUSTIFICATION)), spy)
    assert spy.calls == 1
    assert any("Idempotent handback" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- #
# D4 — a catch-all error boundary must NOT swallow side_effect_ungated (wire-screen lesson)
# --------------------------------------------------------------------------- #
def _catch_all_over_apply_repair() -> str:
    xml = (Path(settings.SEED_DIR) / "wire-repair.bpmn").read_text()
    boundary = (
        '<bpmn:boundaryEvent id="BndAny" attachedToRef="Task_ApplyRepair">'
        '<bpmn:errorEventDefinition/></bpmn:boundaryEvent>'
        '<bpmn:sequenceFlow id="Flow_Any" sourceRef="BndAny" targetRef="End_Returned"/>'
    )
    return xml.replace("</bpmn:process>", boundary + "</bpmn:process>")


def _bundle_with_apply_repair_ungated() -> PackBundle:
    b = PackBundle.from_seed_dir(settings.SEED_DIR)
    xml = _catch_all_over_apply_repair()
    model, findings = parse(xml, b.manifest.process.process_id, profile="error_boundary")
    assert [f.code for f in findings if f.severity == "error"] == []
    b.bpmn_model, b.bpmn_xml = model, xml
    # Simulate a hand-edited / out-of-band manifest: Task_ApplyRepair (side-effectful cap.payment.apply_repair)
    # dropped to hitl 'none' with NO waiver — exactly the state the registry would reject but the runtime must
    # not trust blindly.
    mb = next(x for x in b.manifest.bindings if x.element_id == "Task_ApplyRepair")
    mb.hitl = None
    assert getattr(mb, "side_effect_waiver", None) is None
    return b


def test_catch_all_boundary_does_not_swallow_side_effect_ungated():
    b = _bundle_with_apply_repair_ungated()
    app = compile_graph(b, stub_executor(), simulation=True, checkpointer=MemorySaver(),
                        profile="error_boundary")
    env = make_envelope("AC01")
    env["reason_codes"] = ["AC01"]
    env["exception_id"] = "EXC-CLEAN"
    init = initial_state(envelope=env, trace={"correlation_id": "c"},
                         pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"})
    # a catch-all error boundary IS attached to Task_ApplyRepair; if it could swallow the failure, drive() would
    # return outcome End_Returned. Instead the NodeExecutionError propagates as a hard failure — never masked.
    with pytest.raises(Exception) as ei:
        drive(app, {"configurable": {"thread_id": "se_ungated_ca"}}, init)
    assert getattr(ei.value, "reason", None) == "side_effect_ungated"


# --------------------------------------------------------------------------- #
# D5 — compiler refuses a side-effectful multi-instance host (ADR-065 Part E)
# --------------------------------------------------------------------------- #
def _mi_xml_record_resolution() -> str:
    xml = (Path(settings.SEED_DIR) / "wire-repair.bpmn").read_text()
    open_tag = '<bpmn:serviceTask id="Task_RecordResolution" name="Record resolution &amp; evidence">'
    assert open_tag in xml
    mi = ('<bpmn:multiInstanceLoopCharacteristics><bpmn:loopCardinality>2'
          '</bpmn:loopCardinality></bpmn:multiInstanceLoopCharacteristics>')
    return xml.replace(open_tag, open_tag + mi)


def test_side_effectful_multi_instance_host_refused_at_compile():
    b = PackBundle.from_seed_dir(settings.SEED_DIR)
    xml = _mi_xml_record_resolution()
    model, _ = parse(xml, b.manifest.process.process_id, profile="common_executable")
    assert "Task_RecordResolution" in model.multi_instance
    b.bpmn_model, b.bpmn_xml = model, xml
    # flip the MI host's capability to side-effectful (a manifest that didn't come through the registry)
    cid = "cap.payment.record_resolution"
    b.descriptors[cid] = b.descriptors[cid].model_copy(update={"side_effect": SideEffect.SIDE_EFFECTFUL})
    with pytest.raises(CompilerError, match="side-effectful|multi-instance"):
        compile_graph(b, stub_executor(), simulation=True, checkpointer=MemorySaver(),
                      profile="common_executable")
