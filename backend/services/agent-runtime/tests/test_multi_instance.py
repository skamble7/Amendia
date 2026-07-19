# tests/test_multi_instance.py
"""ADR-036 / Backlog #3 — multi-instance activities in the agent-runtime engine.

Two layers:
  * mechanism (direct node factories): parallel Send fan-out → index-ordered list/indexed aggregation,
    the no-clobber guarantee, sequential loop + completionCondition early-exit, collection vs cardinality.
  * end-to-end through the real compiler + seed bundle: a task turned multi-instance runs N times and
    aggregates, both parallel and sequential; refused under common_subset and when HITL-gated.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from amendia_bpmn import MultiInstance, parse
from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.compiler import CompilerError, compile_graph
from app.engine.executor import InProcessExecutor
from app.engine.executor.core import execute_capability
from app.engine.multi_instance import (
    make_mi_dispatch_node,
    make_mi_fan_out,
    make_mi_iteration_node,
    make_mi_join_node,
    make_sequential_mi_node,
    mi_node_ids,
)
from app.engine.state import ProcessState, initial_state
from app.engine.task_runner import IOSpec, NodeContext, OutputSpec
from tests._wire import drive, make_envelope

OUT_KEY = "art.screening"


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _ctx(*, inputs=None, out_schema=None, cap="cap.screen") -> NodeContext:
    outs = [OutputSpec(name="screening", artifact_key=OUT_KEY, schema_ref=f"{OUT_KEY}@1.0.0",
                       json_schema=out_schema or {"type": "object"})]
    return NodeContext(
        element_id="Screen", element_kind="serviceTask", hitl_mode="none", role=None,
        executor_type="capability", descriptor=SimpleNamespace(capability_id=cap),
        inputs=inputs or [], outputs=outs,
    )


class FakeIterExecutor:
    """Returns a per-iteration output from ``produce(index, item, inputs)`` — the ``Executor`` seam."""

    def __init__(self, produce):
        self._produce = produce

    def execute(self, descriptor, inputs, ctx):
        i = ctx.extras["mi_index"]
        item = ctx.extras.get("mi_item")
        return {"outputs": {OUT_KEY: self._produce(i, item, inputs)}, "log": f"it{i}"}


def _parallel_graph(ctx, mi, executor):
    g = StateGraph(ProcessState)
    iter_id, join_id = mi_node_ids(ctx.element_id)
    g.add_node(ctx.element_id, make_mi_dispatch_node(ctx.element_id))
    g.add_node(iter_id, make_mi_iteration_node(ctx, executor, simulation=False, host=ctx.element_id, mi=mi))
    g.add_node(join_id, make_mi_join_node(ctx, host=ctx.element_id, mi=mi))
    g.add_node("end", lambda s: {"outcome": "done"})
    g.add_edge(START, ctx.element_id)
    g.add_conditional_edges(ctx.element_id, make_mi_fan_out(ctx.element_id, mi), [iter_id, join_id])
    g.add_edge(iter_id, join_id)
    g.add_edge(join_id, "end")
    g.add_edge("end", END)
    return g.compile(checkpointer=MemorySaver())


def _seq_graph(ctx, mi, executor):
    g = StateGraph(ProcessState)
    g.add_node(ctx.element_id, make_sequential_mi_node(ctx, executor, simulation=False, host=ctx.element_id, mi=mi))
    g.add_node("end", lambda s: {"outcome": "done"})
    g.add_edge(START, ctx.element_id)
    g.add_edge(ctx.element_id, "end")
    g.add_edge("end", END)
    return g.compile(checkpointer=MemorySaver())


def _run(app, artifacts=None, tid="mi"):
    init = initial_state(envelope={}, trace={}, pack={})
    init["artifacts"] = artifacts or {}
    return app.invoke(init, {"configurable": {"thread_id": tid}})


# --------------------------------------------------------------------------- #
# Parallel MI
# --------------------------------------------------------------------------- #
def test_parallel_list_default_index_ordered():
    mi = MultiInstance(attached_to="Screen", is_sequential=False, cardinality=3)
    ex = FakeIterExecutor(lambda i, item, inp: {"idx": i})
    r = _run(_parallel_graph(_ctx(), mi, ex))
    # aggregated as a single list under the binding name, in INDEX order (not completion order):
    assert r["artifacts"]["screening"] == [{"idx": 0}, {"idx": 1}, {"idx": 2}]
    assert r["outcome"] == "done"
    # one actor_log entry per iteration, each tagged with its index
    mi_entries = [e for e in r["actor_log"] if e["element_id"] == "Screen"]
    assert sorted(e["exec_meta"]["mi_index"] for e in mi_entries) == [0, 1, 2]


def test_parallel_over_collection_injects_item():
    mi = MultiInstance(attached_to="Screen", is_sequential=False, collection_ref="parties", item_name="party")
    ex = FakeIterExecutor(lambda i, item, inp: {"party": item, "seen": inp.get("party")})
    r = _run(_parallel_graph(_ctx(), mi, ex), artifacts={"parties": ["A", "B", "C"]})
    got = r["artifacts"]["screening"]
    assert [g["party"] for g in got] == ["A", "B", "C"]         # index order over the collection
    assert [g["seen"] for g in got] == ["A", "B", "C"]         # item injected under item_name into inputs


def test_parallel_indexed_aggregation_keeps_scoped_keys():
    mi = MultiInstance(attached_to="Screen", is_sequential=False, cardinality=2, aggregation="indexed")
    ex = FakeIterExecutor(lambda i, item, inp: {"idx": i})
    r = _run(_parallel_graph(_ctx(), mi, ex))
    assert r["artifacts"]["screening#0"] == {"idx": 0}
    assert r["artifacts"]["screening#1"] == {"idx": 1}
    assert "screening" not in r["artifacts"]  # no bare-binding list in indexed mode


def test_parallel_no_clobber_both_iterations_survive():
    # The crux: two iterations produce a DIFFERENT value for the same output binding. Without the
    # index-scoped mi_results channel, the last-wins merge_dicts on the bare binding would keep only
    # one. Scoping preserves both.
    mi = MultiInstance(attached_to="Screen", is_sequential=False, cardinality=2)
    ex = FakeIterExecutor(lambda i, item, inp: {"v": f"iteration-{i}"})
    r = _run(_parallel_graph(_ctx(), mi, ex))
    assert r["artifacts"]["screening"] == [{"v": "iteration-0"}, {"v": "iteration-1"}]
    assert len({tuple(sorted(x.items())) for x in r["artifacts"]["screening"]}) == 2  # distinct, both kept


def test_parallel_empty_collection_aggregates_to_empty_list():
    mi = MultiInstance(attached_to="Screen", is_sequential=False, collection_ref="parties")
    ex = FakeIterExecutor(lambda i, item, inp: {"idx": i})
    r = _run(_parallel_graph(_ctx(), mi, ex), artifacts={"parties": []})
    assert r["artifacts"]["screening"] == []           # N == 0 routes straight to the join
    assert r["outcome"] == "done"


def test_parallel_iteration_output_validated_against_schema():
    # A closed schema requiring "verdict"; an iteration omitting it fails the node (schema_invalid).
    schema = {"type": "object", "required": ["verdict"], "additionalProperties": False,
              "properties": {"verdict": {"type": "string"}}}
    mi = MultiInstance(attached_to="Screen", is_sequential=False, cardinality=2)
    ex = FakeIterExecutor(lambda i, item, inp: {"nope": i})  # missing required 'verdict'
    with pytest.raises(Exception):
        _run(_parallel_graph(_ctx(out_schema=schema), mi, ex))


# --------------------------------------------------------------------------- #
# Sequential MI
# --------------------------------------------------------------------------- #
def test_sequential_list_in_order():
    mi = MultiInstance(attached_to="Screen", is_sequential=True, cardinality=3)
    ex = FakeIterExecutor(lambda i, item, inp: {"idx": i})
    r = _run(_seq_graph(_ctx(), mi, ex))
    assert r["artifacts"]["screening"] == [{"idx": 0}, {"idx": 1}, {"idx": 2}]


def test_sequential_completion_condition_early_exit():
    # completionCondition true after item index 1 → only 2 iterations run.
    mi = MultiInstance(attached_to="Screen", is_sequential=True, collection_ref="parties",
                       item_name="party", completion_condition='screening.stop == "yes"')
    ex = FakeIterExecutor(lambda i, item, inp: {"stop": "yes" if item == "B" else "no"})
    r = _run(_seq_graph(_ctx(), mi, ex), artifacts={"parties": ["A", "B", "C", "D"]})
    got = r["artifacts"]["screening"]
    assert len(got) == 2 and got[-1]["stop"] == "yes"     # early exit after the 2nd (index 1)
    assert len([e for e in r["actor_log"] if e["element_id"] == "Screen"]) == 2


def test_sequential_cardinality_only_uses_index():
    mi = MultiInstance(attached_to="Screen", is_sequential=True, cardinality=2)
    ex = FakeIterExecutor(lambda i, item, inp: {"n": i})
    r = _run(_seq_graph(_ctx(), mi, ex))
    assert r["artifacts"]["screening"] == [{"n": 0}, {"n": 1}]


def test_sequential_and_parallel_identical_for_same_inputs():
    seq = MultiInstance(attached_to="Screen", is_sequential=True, cardinality=3)
    par = MultiInstance(attached_to="Screen", is_sequential=False, cardinality=3)
    ex = FakeIterExecutor(lambda i, item, inp: {"idx": i})
    rs = _run(_seq_graph(_ctx(), seq, ex), tid="s")
    rp = _run(_parallel_graph(_ctx(), par, ex), tid="p")
    assert rs["artifacts"]["screening"] == rp["artifacts"]["screening"]  # index-deterministic


# =========================================================================== #
# End-to-end through the real compiler + seed bundle
# =========================================================================== #
def _mi_xml(*, sequential=False, cardinality=2, host="Task_RecordResolution") -> str:
    xml = (Path(settings.SEED_DIR) / "wire-repair.bpmn").read_text()
    open_tag = f'<bpmn:serviceTask id="{host}" name="Record resolution &amp; evidence">'
    seq = ' isSequential="true"' if sequential else ""
    mi = (f'<bpmn:multiInstanceLoopCharacteristics{seq}>'
          f'<bpmn:loopCardinality>{cardinality}</bpmn:loopCardinality>'
          f'</bpmn:multiInstanceLoopCharacteristics>')
    assert open_tag in xml
    return xml.replace(open_tag, open_tag + mi)


def _mi_bundle(xml: str) -> PackBundle:
    b = PackBundle.from_seed_dir(settings.SEED_DIR)
    model, findings = parse(xml, b.manifest.process.process_id, profile="common_executable")
    assert [f.code for f in findings if f.severity == "error"] == []
    assert "Task_RecordResolution" in model.multi_instance
    b.bpmn_model = model
    b.bpmn_xml = xml
    return b


class MIHybridExecutor:
    """Real sim for every task except the MI host, which returns a valid resolution per iteration."""

    def __init__(self, mi_cap):
        self._mi_cap = mi_cap
        self._fallback = InProcessExecutor()

    def execute(self, descriptor, inputs, ctx):
        if descriptor.capability_id == self._mi_cap:
            i = ctx.extras["mi_index"]
            return {"outputs": {"art.payment.resolution_record":
                                {"outcome": "repaired_and_released", "summary": f"iteration {i}"}},
                    "log": f"mi {i}"}
        return self._fallback.execute(descriptor, inputs, ctx)


def _initial():
    return initial_state(envelope=make_envelope("AC01", exception_id="EXC-MI"),
                         trace={"correlation_id": "EXC-MI"},
                         pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"})


def test_e2e_parallel_multi_instance_aggregates_list():
    b = _mi_bundle(_mi_xml(sequential=False, cardinality=2))
    ex = MIHybridExecutor("cap.payment.record_resolution")
    app = compile_graph(b, ex, simulation=True, checkpointer=MemorySaver(), profile="common_executable")
    final, _ = drive(app, {"configurable": {"thread_id": "mi-e2e-par"}}, _initial())
    assert final["outcome"] == "End_Resolved"
    res = final["artifacts"]["resolution"]
    assert isinstance(res, list) and len(res) == 2
    assert [r["summary"] for r in res] == ["iteration 0", "iteration 1"]
    assert len([e for e in final["actor_log"] if e["element_id"] == "Task_RecordResolution"]) == 2


def test_e2e_sequential_multi_instance_aggregates_list():
    b = _mi_bundle(_mi_xml(sequential=True, cardinality=3))
    ex = MIHybridExecutor("cap.payment.record_resolution")
    app = compile_graph(b, ex, simulation=True, checkpointer=MemorySaver(), profile="common_executable")
    final, _ = drive(app, {"configurable": {"thread_id": "mi-e2e-seq"}}, _initial())
    assert final["outcome"] == "End_Resolved"
    assert len(final["artifacts"]["resolution"]) == 3


def test_e2e_refused_under_common_subset():
    b = _mi_bundle(_mi_xml())
    with pytest.raises(CompilerError, match="multi_instance|multi-instance"):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                      profile="common_subset")


def test_e2e_hitl_gated_mi_refused():
    # Task_DraftRepair is review_after → an MI host with a HITL gate is refused (deferred).
    xml = (Path(settings.SEED_DIR) / "wire-repair.bpmn").read_text()
    open_tag = '<bpmn:serviceTask id="Task_DraftRepair" name="Draft repair instruction">'
    assert open_tag in xml
    xml = xml.replace(open_tag, open_tag +
                      '<bpmn:multiInstanceLoopCharacteristics><bpmn:loopCardinality>2'
                      '</bpmn:loopCardinality></bpmn:multiInstanceLoopCharacteristics>')
    b = PackBundle.from_seed_dir(settings.SEED_DIR)
    model, _ = parse(xml, b.manifest.process.process_id, profile="common_executable")
    b.bpmn_model = model
    b.bpmn_xml = xml
    with pytest.raises(CompilerError, match="HITL"):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                      profile="common_executable")
