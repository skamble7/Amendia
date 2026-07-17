# tests/test_parallel_spike.py
"""ADR-027 Phase 2.1 — parallelGateway fork/join execution spike (extend-native go/no-go).

Two layers:
  * end-to-end through the real compiler + seed bundle: the notify+record fan-out compiles and
    runs under the ``parallel`` profile (and is refused under ``common_subset``), with both
    branches' artifacts merged.
  * LangGraph mechanism: fork/join reducer merge, and — the crux — SEVERAL concurrent interrupts
    surface at once but are resolved ONE AT A TIME via id-keyed ``Command(resume={id: value})``
    (the sequentialize decision), plus checkpoint recovery across a fork.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.compiler import CompilerError, compile_graph
from app.engine.executor import InProcessExecutor
from app.engine.state import ProcessState, initial_state
from amendia_bpmn import parse
from tests._wire import drive, make_envelope


# --------------------------------------------------------------------------- #
# Real compiler + seed bundle: the notify+record fan-out as a parallel fork/join.
# --------------------------------------------------------------------------- #

def _parallel_xml() -> str:
    """The standard seed BPMN with Notify ∥ Record turned into a parallelGateway fork/join."""
    xml = (Path(settings.SEED_DIR) / "wire-repair.bpmn").read_text()
    xml = xml.replace(
        '<bpmn:sequenceFlow id="Flow_Apply_Notify" sourceRef="Task_ApplyRepair" targetRef="Task_NotifyParties"/>',
        '<bpmn:parallelGateway id="Gw_Fork"/><bpmn:parallelGateway id="Gw_Join"/>'
        '<bpmn:sequenceFlow id="Flow_Apply_Fork" sourceRef="Task_ApplyRepair" targetRef="Gw_Fork"/>'
        '<bpmn:sequenceFlow id="Flow_Fork_Notify" sourceRef="Gw_Fork" targetRef="Task_NotifyParties"/>'
        '<bpmn:sequenceFlow id="Flow_Fork_Record" sourceRef="Gw_Fork" targetRef="Task_RecordResolution"/>'
        '<bpmn:sequenceFlow id="Flow_Join_Resolved" sourceRef="Gw_Join" targetRef="End_Resolved"/>')
    xml = xml.replace(
        '<bpmn:sequenceFlow id="Flow_Notify_Record" sourceRef="Task_NotifyParties" targetRef="Task_RecordResolution"/>',
        '<bpmn:sequenceFlow id="Flow_Notify_Join" sourceRef="Task_NotifyParties" targetRef="Gw_Join"/>')
    xml = xml.replace(
        '<bpmn:sequenceFlow id="Flow_Record_Resolved" sourceRef="Task_RecordResolution" targetRef="End_Resolved"/>',
        '<bpmn:sequenceFlow id="Flow_Record_Join" sourceRef="Task_RecordResolution" targetRef="Gw_Join"/>')
    return xml


def _parallel_bundle() -> PackBundle:
    b = PackBundle.from_seed_dir(settings.SEED_DIR)
    model, findings = parse(_parallel_xml(), b.manifest.process.process_id, profile="parallel")
    assert [f.code for f in findings if f.severity == "error"] == []
    assert set(model.parallel_gateways) == {"Gw_Fork", "Gw_Join"}
    b.bpmn_model = model
    b.bpmn_xml = _parallel_xml()
    return b


def test_common_subset_refuses_parallel():
    b = _parallel_bundle()
    with pytest.raises(CompilerError, match="parallelGateway"):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(), profile="common_subset")


def test_parallel_profile_compiles_fork_and_join():
    b = _parallel_bundle()
    app = compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(), profile="parallel")
    nodes = set(app.get_graph().nodes)
    assert {"Gw_Fork", "Gw_Join", "Task_NotifyParties", "Task_RecordResolution"} <= nodes


def test_parallel_execution_runs_both_branches():
    b = _parallel_bundle()
    app = compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(), profile="parallel")
    init = initial_state(
        envelope=make_envelope("AC01", exception_id="EXC-PAR"),
        trace={"correlation_id": "EXC-PAR"},
        pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"},
    )
    final, _ = drive(app, {"configurable": {"thread_id": "pi-par"}}, init)
    assert final["outcome"] == "End_Resolved"
    acted = {e["element_id"] for e in final["actor_log"]}
    assert {"Task_NotifyParties", "Task_RecordResolution"} <= acted  # both branches ran + merged


# --------------------------------------------------------------------------- #
# LangGraph mechanism: reducer merge + serialized multi-interrupt + recovery.
# --------------------------------------------------------------------------- #

def _fork_graph(gates: set[str]):
    """fork → A ∥ B → join → end. Branches in ``gates`` raise interrupt()."""
    g = StateGraph(ProcessState)

    def _branch(name):
        def b(_s):
            if name in gates:
                interrupt({"element_id": name})
            return {"artifacts": {name: {"done": True}}, "actor_log": [{"element_id": name}]}
        b.__name__ = name
        return b

    g.add_node("fork", lambda _s: {})
    g.add_node("A", _branch("A"))
    g.add_node("B", _branch("B"))
    g.add_node("join", lambda _s: {})
    g.add_node("end", lambda _s: {"outcome": "done"})
    g.add_edge(START, "fork")
    g.add_edge("fork", "A")
    g.add_edge("fork", "B")
    g.add_edge("A", "join")
    g.add_edge("B", "join")
    g.add_edge("join", "end")
    g.add_edge("end", END)
    return g.compile(checkpointer=MemorySaver())


def _init():
    return initial_state(envelope={}, trace={}, pack={})


def test_mechanism_fork_join_merges_concurrent_writes():
    r = _fork_graph(set()).invoke(_init(), {"configurable": {"thread_id": "m0"}})
    # artifacts dict-merge + actor_log append reducers merge both concurrent branch writes.
    assert r["artifacts"]["A"]["done"] and r["artifacts"]["B"]["done"]
    assert {e["element_id"] for e in r["actor_log"]} == {"A", "B"}
    assert r["outcome"] == "done"


def test_mechanism_two_concurrent_gates_serialize_via_id_keyed_resume():
    app = _fork_graph({"A", "B"})
    cfg = {"configurable": {"thread_id": "m2"}}
    r = app.invoke(_init(), cfg)
    # BOTH interrupts surface at once — but each must be resolved by its own id, one at a time.
    assert len(r["__interrupt__"]) == 2
    first = r["__interrupt__"][0]
    r = app.invoke(Command(resume={first.id: {"decision": "approve"}}), cfg)
    remaining = r.get("__interrupt__", []) if "__interrupt__" in r else []
    assert len(remaining) == 1  # the other gate is still pending (one open at a time)
    r = app.invoke(Command(resume={remaining[0].id: {"decision": "approve"}}), cfg)
    assert r["outcome"] == "done"
    assert r["artifacts"]["A"]["done"] and r["artifacts"]["B"]["done"]


def test_mechanism_recovery_reinvokes_mid_fork():
    app = _fork_graph({"A"})
    cfg = {"configurable": {"thread_id": "m3"}}
    r = app.invoke(_init(), cfg)
    assert "__interrupt__" in r  # parked mid-fork (A gated; B already produced)
    # "crash": re-invoke with None (what engine.recover does) — restores the parallel frontier.
    r = app.invoke(None, cfg)
    assert "__interrupt__" in r  # same pending gate after recovery
    iid = r["__interrupt__"][0].id
    r = app.invoke(Command(resume={iid: {"decision": "approve"}}), cfg)
    assert r["outcome"] == "done"
    assert r["artifacts"]["A"]["done"] and r["artifacts"]["B"]["done"]


# --------------------------------------------------------------------------- #
# ADR-027 Phase 2.5 — runtime load guard: a lower-ranked runtime refuses a pack whose
# required_execution_profile (pinned in the resolution sidecar at activation) it can't run.
# --------------------------------------------------------------------------- #

def _seed_manifest_doc(status="active"):
    import json
    doc = json.loads((Path(settings.SEED_DIR) / "manifest.json").read_text())
    doc["status"] = status
    return doc


class _ProfileRegistry:
    """Minimal registry stub: the guard fires after get_resolution, before get_bpmn."""

    def __init__(self, required_profile):
        self._required = required_profile

    async def get_pack(self, pack_key, version):
        return _seed_manifest_doc()

    async def get_resolution(self, pack_key, version):
        return {"capabilities": {}, "artifacts": {}, "bindings": [],
                "required_execution_profile": self._required}

    async def get_bpmn(self, pack_key, version):
        import json
        doc = json.loads((Path(settings.SEED_DIR) / "manifest.json").read_text())
        return (Path(settings.SEED_DIR) / doc["process"]["bpmn_file"]).read_text()


class _Settings:
    def __init__(self, profile):
        self.EXECUTION_PROFILE = profile


def _engine(registry, profile):
    from app.engine.engine import ProcessEngine
    return ProcessEngine(
        registry=registry, instance_repo=None, hitl_repo=None, publisher=None,
        settings=_Settings(profile), checkpointer=MemorySaver(),
    )


async def test_common_subset_runtime_refuses_parallel_pack():
    from app.engine.engine import PackRequiresProfile
    eng = _engine(_ProfileRegistry("parallel"), "common_subset")
    with pytest.raises(PackRequiresProfile) as ei:
        await eng.load_bundle("wire-repair-standard", "1.0.0")
    assert ei.value.required == "parallel" and ei.value.runtime == "common_subset"


async def test_parallel_runtime_runs_common_subset_pack():
    # superset runtime runs a subset pack (>= hierarchy): guard passes, load proceeds past it.
    eng = _engine(_ProfileRegistry("common_subset"), "parallel")
    bundle = await eng.load_bundle("wire-repair-standard", "1.0.0")
    assert bundle.required_execution_profile == "common_subset"


async def test_missing_required_profile_defaults_common_subset():
    # older packs with no pin → treated as common_subset, loadable by any runtime.
    class _NoPin(_ProfileRegistry):
        async def get_resolution(self, pack_key, version):
            return {"capabilities": {}, "artifacts": {}, "bindings": []}

    eng = _engine(_NoPin("common_subset"), "common_subset")
    bundle = await eng.load_bundle("wire-repair-standard", "1.0.0")
    assert bundle.required_execution_profile == "common_subset"
