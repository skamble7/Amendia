# tests/test_readmodels.py
"""ADR-058 Phase C — the decision-trail + lineage read-model assembly (pure, no ClickHouse)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import orjson

from app.readmodels import build_decision_trail, build_lineage


def _decided(el, by, role, decision, when, sod=None, comment=None):
    return {
        "element_id": el, "decided_by": by, "role": role, "decision": decision,
        "sod_satisfied": sod, "occurred_at": when,
        "payload": orjson.dumps({"comment": comment}).decode() if comment is not None else "",
    }


def _artifact(el, ak, sr, *, human, actor_kind):
    return {"element_id": el, "artifact_key": ak, "schema_ref": sr,
            "actor_kind": actor_kind, "authored_by_human": 1 if human else 0}


def test_decision_trail_ordered_with_refs_sod_and_comment():
    t0 = datetime(2026, 8, 4, tzinfo=timezone.utc)
    decided = [
        _decided("Gate_A", "analyst-1", "role.ops.analyst", "approve", t0,
                 sod=None, comment="looks good"),
        _decided("Gate_B", "approver-1", "role.ops.approver", "approve", t0 + timedelta(minutes=1),
                 sod=1, comment=None),
    ]
    artifacts = [
        _artifact("Gate_A", "art.x", "art.x@1.0.0", human=True, actor_kind="human"),
        _artifact("Gate_B", "art.y", "art.y@2.0.0", human=True, actor_kind="human"),
    ]
    trail = build_decision_trail(decided, artifacts)
    assert [g["element_id"] for g in trail] == ["Gate_A", "Gate_B"]     # occurred_at order
    a = trail[0]
    assert a["decided_by"] == "analyst-1" and a["role"] == "role.ops.analyst"
    assert a["decision"] == "approve" and a["comment"] == "looks good"
    assert a["sod_satisfied"] is None
    assert a["approved"] == {"artifact_key": "art.x", "schema_ref": "art.x@1.0.0"}
    assert a["proposed"]["artifact_key"] == "art.x"                     # single commit → proposed==approved ref
    assert trail[1]["sod_satisfied"] is True                           # four-eyes honored


def test_decision_trail_splits_capability_draft_from_human_approved():
    t0 = datetime(2026, 8, 4, tzinfo=timezone.utc)
    decided = [_decided("Gate_M", "u1", "role.ops.analyst", "edit_and_approve", t0)]
    artifacts = [
        _artifact("Gate_M", "art.z", "art.z@1.0.0", human=False, actor_kind="capability"),  # agent draft
        _artifact("Gate_M", "art.z", "art.z@1.0.0", human=True, actor_kind="human"),         # human output
    ]
    trail = build_decision_trail(decided, artifacts)
    assert trail[0]["proposed"]["artifact_key"] == "art.z"   # the capability-side draft ref
    assert trail[0]["approved"]["artifact_key"] == "art.z"   # the human-side approved ref


def test_lineage_builds_artifact_dag_with_edges():
    spans = [
        {"span_id": "s1", "element_id": "A", "artifact_key": "art.a", "schema_ref": "art.a@1.0.0",
         "actor_kind": "capability", "link_span_ids": []},
        {"span_id": "s2", "element_id": "B", "artifact_key": "art.b", "schema_ref": "art.b@1.0.0",
         "actor_kind": "capability", "link_span_ids": ["s1"]},                 # B consumes A
        {"span_id": "sctrl", "element_id": "End", "artifact_key": "", "link_span_ids": ["s2"]},  # control span → not a node
    ]
    g = build_lineage("trace-1", spans, artifact_rows=[
        {"artifact_key": "art.a", "authored_by_human": 0},
        {"artifact_key": "art.b", "authored_by_human": 1},
    ])
    assert g["trace_id"] == "trace-1"
    node_ids = {n["span_id"] for n in g["nodes"]}
    assert node_ids == {"s1", "s2"}                              # the control span is excluded
    assert {n["artifact_key"]: n["authored_by_human"] for n in g["nodes"]} == {"art.a": False, "art.b": True}
    assert g["edges"] == [{"from_span": "s1", "to_span": "s2",
                           "from_artifact_key": "art.a", "to_artifact_key": "art.b"}]


def test_lineage_includes_mi_join_fan_in():
    # Two MI iterations produce the same artifact_key; the join links back to BOTH → fan-in visible
    # because nodes are span-keyed (iterations are distinct nodes).
    spans = [
        {"span_id": "it0", "element_id": "H__mi_iter", "artifact_key": "art.k", "link_span_ids": []},
        {"span_id": "it1", "element_id": "H__mi_iter", "artifact_key": "art.k", "link_span_ids": []},
        {"span_id": "jn", "element_id": "H__mi_join", "artifact_key": "art.k", "link_span_ids": ["it0", "it1"]},
        {"span_id": "cons", "element_id": "C", "artifact_key": "art.c", "link_span_ids": ["jn"]},
    ]
    g = build_lineage("t", spans, artifact_rows=[])
    edges = {(e["from_span"], e["to_span"]) for e in g["edges"]}
    assert ("it0", "jn") in edges and ("it1", "jn") in edges      # the fan-in
    assert ("jn", "cons") in edges                                 # join → downstream consumer
    assert len([n for n in g["nodes"] if n["element_id"] == "H__mi_iter"]) == 2


def test_trace_tree_computes_depth_and_is_orphan_safe():
    from app.readmodels import build_trace_tree
    spans = [
        {"span_id": "root", "parent_span_id": "", "name": "instance", "start_ns": 1, "duration_ns": 10},
        {"span_id": "a", "parent_span_id": "root", "name": "Task_A", "start_ns": 2, "duration_ns": 3,
         "element_id": "Task_A", "actor_kind": "capability"},
        {"span_id": "b", "parent_span_id": "a", "name": "Task_B", "start_ns": 3, "duration_ns": 2},
        {"span_id": "orphan", "parent_span_id": "missing", "name": "X", "start_ns": 4, "duration_ns": 1},
    ]
    tree = build_trace_tree("t", spans)
    depth = {s["span_id"]: s["depth"] for s in tree["spans"]}
    assert depth == {"root": 0, "a": 1, "b": 2, "orphan": 0}   # missing parent → depth 0 (no crash)
    assert tree["trace_id"] == "t"
    a = next(s for s in tree["spans"] if s["span_id"] == "a")
    assert a["element_id"] == "Task_A" and a["actor_kind"] == "capability"
