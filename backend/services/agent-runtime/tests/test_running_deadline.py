# tests/test_running_deadline.py
"""ADR-040 — cooperative cancellation: an interrupting timer boundary on a running serviceTask.

A capability serviceTask with a timer boundary self-enforces an in-process SLA deadline (injected
clock). Within the deadline it commits normally; on breach it commits nothing, marks the boundary
channel, and routes to the timer target — the instance stays running. The token is threaded to the
capability and honored cooperatively. Node-level tests control the clock + executor directly; a graph
test proves end-to-end routing.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver

from amendia_bpmn import parse
from amendia_bpmn.model import BoundaryTimer, TimerDef
from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.compiler import CompilerError, compile_graph
from app.engine.executor import InProcessExecutor
from app.engine.state import initial_state
from app.engine.task_runner import NodeContext, OutputSpec, make_task_node
from tests._wire import drive, make_envelope


def _clock_jumping(after: float = 1e9):
    """A clock that returns 0.0 on its first read (node entry → deadline) then a value far past the
    deadline on every subsequent read — a deterministic 'the deadline has passed'."""
    calls = {"n": 0}

    def now() -> float:
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else after
    return now


def _ctx(cap="cap.x", side_effect="read_only"):
    return NodeContext(
        element_id="Task_X", element_kind="serviceTask", hitl_mode="none", role=None,
        executor_type="capability",
        descriptor=SimpleNamespace(capability_id=cap, kind=SimpleNamespace(value="skill"),
                                   side_effect=SimpleNamespace(value=side_effect),
                                   constraints=None, idempotent=False),
        outputs=[OutputSpec(name="out", artifact_key="art.x", schema_ref="art.x@1.0.0",
                            json_schema={"type": "object"})],
    )


_BT = BoundaryTimer(id="Sla", attached_to="Task_X", timer=TimerDef("duration", "PT2H"),
                    cancel_activity=True, target="Esc")


class _Fast:
    def execute(self, d, inputs, ctx):
        return {"outputs": {"art.x": {"ok": True}}, "log": "fast"}


class _Blocking:
    """Blocks until cancelled, then records that it honored the token (cooperative)."""

    def __init__(self):
        self.saw_cancel = False

    def execute(self, d, inputs, ctx):
        while not (ctx.cancel is not None and ctx.cancel.cancelled):
            time.sleep(0.002)
        self.saw_cancel = True
        return {"outputs": {"art.x": {"late": True}}, "log": "late (discarded)"}


def _run_node(ctx, executor, *, clock):
    node = make_task_node(ctx, executor, simulation=False, boundary_timer=_BT, clock=clock)
    return node({"envelope": {}, "artifacts": {}}, {"configurable": {"thread_id": "t"}})


# --------------------------------------------------------------------------- #
# Node-level
# --------------------------------------------------------------------------- #
def test_within_deadline_commits_normally():
    out = _run_node(_ctx(), _Fast(), clock=_clock_jumping())
    assert out["artifacts"] == {"out": {"ok": True}}   # committed
    assert "boundary" not in out                        # no SLA breach


def test_deadline_breach_marks_boundary_no_commit():
    ex = _Blocking()
    out = _run_node(_ctx(), ex, clock=_clock_jumping())
    # all-or-nothing: no partial artifact; only the boundary mark, routed by the existing router.
    assert "artifacts" not in out
    assert out["boundary"] == {"Task_X": {"kind": "timer"}}
    entry = out["actor_log"][0]
    assert entry["actor"] == "timer" and entry["kind"] == "timer"
    assert entry["exec_meta"]["sla_breach_seconds"] == 7200.0


def test_cooperative_token_is_honored():
    ex = _Blocking()
    _run_node(_ctx(), ex, clock=_clock_jumping())
    # the abandoned capability sees token.cancelled and returns early (proves the token was threaded)
    for _ in range(50):
        if ex.saw_cancel:
            break
        time.sleep(0.01)
    assert ex.saw_cancel


def test_reentrant_rerun_is_idempotent():
    # simulate recovery re-running the node from the top with the clock past the deadline
    ctx = _ctx()
    a = _run_node(ctx, _Blocking(), clock=_clock_jumping())
    b = _run_node(ctx, _Blocking(), clock=_clock_jumping())
    assert a["boundary"] == b["boundary"] == {"Task_X": {"kind": "timer"}}
    assert "artifacts" not in a and "artifacts" not in b  # never a double-commit


# --------------------------------------------------------------------------- #
# Compiler safety guards
# --------------------------------------------------------------------------- #
def _seed_xml() -> str:
    return (Path(settings.SEED_DIR) / "wire-repair.bpmn").read_text()


def _boundary_on(host: str, *, target="End_Returned") -> str:
    xml = _seed_xml()
    bnd = (f'<bpmn:boundaryEvent id="Sla" attachedToRef="{host}"><bpmn:timerEventDefinition>'
           '<bpmn:timeDuration>PT2H</bpmn:timeDuration></bpmn:timerEventDefinition></bpmn:boundaryEvent>'
           f'<bpmn:sequenceFlow id="Flow_Sla" sourceRef="Sla" targetRef="{target}"/>')
    return xml.replace("</bpmn:process>", bnd + "</bpmn:process>")


def _bundle(xml: str) -> PackBundle:
    b = PackBundle.from_seed_dir(settings.SEED_DIR)
    model, findings = parse(xml, b.manifest.process.process_id, profile="common_executable")
    assert [f.code for f in findings if f.severity == "error"] == []
    b.bpmn_model = model
    b.bpmn_xml = xml
    return b


def test_non_autonomous_host_refused_at_compile():
    # A timer boundary on a HITL-gated serviceTask (Task_ApplyRepair = approve_actions) is refused —
    # the running deadline is for an autonomous (hitl 'none') capability only (ADR-040). (A side-effectful
    # host is refused at registry validation with bpmn_timer_boundary_side_effect_unsupported — see the
    # process-registry suite; side-effectful ⇒ approve_actions, so the hitl guard fires first at compile.)
    b = _bundle(_boundary_on("Task_ApplyRepair"))
    with pytest.raises(CompilerError, match="autonomous"):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                      profile="common_executable")


# --------------------------------------------------------------------------- #
# Graph-level: within deadline (regression) + breach → routes
# --------------------------------------------------------------------------- #
class _HybridBlock:
    """Sim for every capability except the deadlined one, which blocks (to breach the SLA)."""

    def __init__(self, block_cap):
        self._block = block_cap
        self._fallback = InProcessExecutor()

    def execute(self, descriptor, inputs, ctx):
        if descriptor.capability_id == self._block:
            while not (ctx.cancel is not None and ctx.cancel.cancelled):
                time.sleep(0.002)
            return {"outputs": {}, "log": "blocked"}
        return self._fallback.execute(descriptor, inputs, ctx)


def test_graph_within_deadline_completes_normally():
    # Task_EnrichPayment (read_only, hitl none) with a timer boundary; sim enrich is instant → within
    # the deadline → normal completion, no boundary mark (idle-gate + non-boundary paths unchanged).
    b = _bundle(_boundary_on("Task_EnrichPayment"))
    app = compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                        profile="common_executable")
    env = make_envelope("AC01"); env["reason_codes"] = ["AC01"]
    final, _ = drive(app, {"configurable": {"thread_id": "sla-ok"}},
                     initial_state(envelope=env, trace={"correlation_id": "c"},
                                   pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"}))
    assert final["outcome"] == "End_Resolved"
    assert "Task_EnrichPayment" not in (final.get("boundary") or {})


def test_graph_deadline_breach_routes_to_boundary_target():
    b = _bundle(_boundary_on("Task_EnrichPayment", target="End_Returned"))
    ex = _HybridBlock("cap.payment.enrich_investigation")
    app = compile_graph(b, ex, simulation=True, checkpointer=MemorySaver(),
                        profile="common_executable", clock=_clock_jumping())
    env = make_envelope("AC01"); env["reason_codes"] = ["AC01"]
    final, _ = drive(app, {"configurable": {"thread_id": "sla-breach"}},
                     initial_state(envelope=env, trace={"correlation_id": "c"},
                                   pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"}))
    # the running enrich breached its SLA → boundary mark → routed to End_Returned; instance stays running
    assert final["boundary"]["Task_EnrichPayment"] == {"kind": "timer"}
    assert final["outcome"] == "End_Returned"
    assert "dossier" not in final["artifacts"]   # no partial artifact committed
    assert any(e["element_id"] == "Task_EnrichPayment" and e["kind"] == "timer" for e in final["actor_log"])
