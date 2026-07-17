# tests/test_compiler.py
"""Part C: BPMN+manifest+resolution → StateGraph compilation + gateway routing."""
from __future__ import annotations

import copy

import pytest
from langgraph.checkpoint.memory import MemorySaver

from amendia_bpmn import parse
from app.engine import compiler
from app.engine.compiler import CompilerError, compile_graph
from app.engine.executor import InProcessExecutor


def _saver():
    return MemorySaver()


def test_seed_bundle_compiles(bundle):
    app = compile_graph(bundle, InProcessExecutor(), simulation=True, checkpointer=_saver())
    assert app is not None
    # every bound task became a node
    node_ids = set(app.get_graph().nodes)
    for element_id in bundle.bpmn_model.tasks:
        assert element_id in node_ids


def test_compilation_is_deterministic(bundle):
    a = compile_graph(bundle, InProcessExecutor(), simulation=True, checkpointer=_saver())
    b = compile_graph(bundle, InProcessExecutor(), simulation=True, checkpointer=_saver())
    assert list(a.get_graph().nodes) == list(b.get_graph().nodes)
    edges_a = sorted((e.source, e.target) for e in a.get_graph().edges)
    edges_b = sorted((e.source, e.target) for e in b.get_graph().edges)
    assert edges_a == edges_b


@pytest.mark.parametrize(
    "verdict,expected",
    [
        ("repairable", "Task_DraftRepair"),
        ("unrepairable", "Task_DraftReturn"),
        ("needs_info", "Task_ObtainInfo"),
        ("something_else", "Task_ObtainInfo"),  # no match → default flow
    ],
)
def test_gateway_routing_table(bundle, verdict, expected):
    model = bundle.bpmn_model
    router, path_map = compiler._build_gateway_router(bundle, model, "Gateway_Repairable", lambda t: t)
    state = {"artifacts": {"beneficiary": {"repair_verdict": verdict}}}
    assert router(state) == expected
    assert expected in path_map


def test_parallel_gateway_rejected(bundle):
    bad = copy.copy(bundle)
    bad.bpmn_model = copy.deepcopy(bundle.bpmn_model)
    bad.bpmn_model.parallel_gateways = ["Gateway_Fake"]
    with pytest.raises(CompilerError, match="parallelGateway"):
        compile_graph(bad, InProcessExecutor(), simulation=True, checkpointer=_saver())


def test_unparseable_condition_rejected(bundle):
    bad = copy.copy(bundle)
    bad.bpmn_model = copy.deepcopy(bundle.bpmn_model)
    for fl in bad.bpmn_model.flows:
        if fl.id == "Flow_Repairable":
            fl.condition_expr = "beneficiary.repair_verdict in [1,2,3]"  # unsupported
    with pytest.raises(CompilerError, match="Gateway_Repairable"):
        compile_graph(bad, InProcessExecutor(), simulation=True, checkpointer=_saver())


def test_documented_element_is_warning_not_error():
    # ADR-027: a boundary event is documented (warning), not a hard-error unsupported element.
    xml = """<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
      <bpmn:process id="P">
        <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
        <bpmn:boundaryEvent id="b" attachedToRef="s"/>
        <bpmn:endEvent id="e"><bpmn:incoming>f1</bpmn:incoming></bpmn:endEvent>
        <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="e"/>
      </bpmn:process>
    </bpmn:definitions>"""
    model, findings = parse(xml, "P")
    assert model is not None
    assert [f for f in findings if f.severity == "error"] == []   # runtime reject filter → empty
    assert any(f.code == "bpmn_documented_element" and f.severity == "warning" for f in findings)


def test_documented_element_ignored_by_compiler(bundle):
    # An off-path documented element is retained on the model but never touched by the compiler.
    from amendia_bpmn import ClassifiedElement

    b = copy.copy(bundle)
    b.bpmn_model = copy.deepcopy(bundle.bpmn_model)
    b.bpmn_model.elements.append(ClassifiedElement(id="Lane_X", kind="laneSet", tier="documented"))
    app = compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=_saver())
    assert app is not None
