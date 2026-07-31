# tests/test_flowgraph.py
"""ADR-052 — the BPMN flow-graph reachability/dominance primitives used for loop-back input optionality.

Purely structural, domain-neutral: a producer is a *guaranteed predecessor* of a consumer iff it dominates the
consumer (on every path from start) AND the consumer can't loop back to it. Everything else (loop-back, or a
branch-only producer) is NOT guaranteed → the consuming input must be optional.
"""
from __future__ import annotations

from app.services.copilot.flowgraph import FlowGraph, build_flow_graph


def _linear() -> FlowGraph:
    # Start → A → B → C → End
    return FlowGraph([("Start", "A"), ("A", "B"), ("B", "C"), ("C", "End")], "Start")


def _loopback() -> FlowGraph:
    # Start → Assess → Gw → (needs_info) ObtainInfo → Assess ; Gw → End  (ObtainInfo runs AFTER Assess, loops in)
    return FlowGraph([("Start", "Assess"), ("Assess", "Gw"),
                      ("Gw", "ObtainInfo"), ("ObtainInfo", "Assess"), ("Gw", "End")], "Start")


def _branch() -> FlowGraph:
    # Start → Split → (A → Join) | (B → Join) → End  — A and B each run on only one branch
    return FlowGraph([("Start", "Split"), ("Split", "A"), ("Split", "B"),
                      ("A", "Join"), ("B", "Join"), ("Join", "End")], "Start")


def test_linear_upstream_is_a_guaranteed_predecessor():
    g = _linear()
    assert g.dominates("A", "C") is True
    assert g.can_reach("C", "A") is False
    assert g.guaranteed_predecessor("A", "C") is True          # A is strictly upstream of C
    assert g.guaranteed_predecessor("C", "A") is False         # C is downstream, not a predecessor of A


def test_loopback_producer_is_not_a_guaranteed_predecessor():
    g = _loopback()
    # ObtainInfo produces the info Assess reads, but it only runs on the loop-back — it does NOT dominate Assess
    # (Assess runs first) and Assess CAN reach it (needs-info branch). So it is not a guaranteed predecessor.
    assert g.dominates("ObtainInfo", "Assess") is False
    assert g.can_reach("Assess", "ObtainInfo") is True
    assert g.guaranteed_predecessor("ObtainInfo", "Assess") is False
    # The start event is on every path — it dominates everything reachable.
    assert g.dominates("Start", "Assess") is True


def test_branch_only_producer_is_not_guaranteed():
    g = _branch()
    # A runs only on one branch → it does NOT dominate Join (the B branch reaches Join without A).
    assert g.dominates("A", "Join") is False
    assert g.guaranteed_predecessor("A", "Join") is False
    # Split is on every path to Join → guaranteed.
    assert g.guaranteed_predecessor("Split", "Join") is True


def test_build_flow_graph_from_semantics():
    class _F:
        def __init__(self, s, t):
            self.source, self.target = s, t

    class _N:
        def __init__(self, i, k):
            self.id, self.kind = i, k

    sem = type("Sem", (), {
        "sequence_flows": [_F("Start", "A"), _F("A", "End")],
        "flow_nodes": [_N("Start", "startEvent"), _N("A", "serviceTask"), _N("End", "endEvent")],
    })()
    g = build_flow_graph(sem)
    assert g is not None and g.start == "Start"
    assert g.guaranteed_predecessor("A", "End") is True
    # No sequence flows → nothing to reason about → None.
    assert build_flow_graph(type("Sem", (), {"sequence_flows": [], "flow_nodes": []})()) is None
