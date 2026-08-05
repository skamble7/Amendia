# tests/test_readmodels_api.py
"""ADR-058 Phase C — the decision-trail + lineage HTTP endpoints (fake reader; no ClickHouse)."""
from __future__ import annotations

from datetime import datetime, timezone

import orjson
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_reader
from app.routers import audit


class FakeReader:
    def __init__(self, *, decided=None, artifacts=None, trace_id="", spans=None):
        self._decided = decided or []
        self._artifacts = artifacts or []
        self._trace_id = trace_id
        self._spans = spans or []

    async def decided_rows(self, cid):
        return self._decided

    async def artifact_rows(self, cid):
        return self._artifacts

    async def trace_id_for(self, cid):
        return self._trace_id

    async def trace_spans(self, tid):
        return self._spans


def _client(reader):
    app = FastAPI()
    app.include_router(audit.router)
    app.dependency_overrides[get_reader] = lambda: reader
    return TestClient(app)


def test_decision_trail_endpoint():
    t0 = datetime(2026, 8, 4, tzinfo=timezone.utc)
    reader = FakeReader(
        decided=[{"element_id": "Gate_A", "decided_by": "u1", "role": "role.ops.analyst",
                  "decision": "approve", "sod_satisfied": 1, "occurred_at": t0,
                  "payload": orjson.dumps({"comment": "ok"}).decode()}],
        artifacts=[{"element_id": "Gate_A", "artifact_key": "art.x", "schema_ref": "art.x@1.0.0",
                    "actor_kind": "human", "authored_by_human": 1}],
    )
    r = _client(reader).get("/audit/instances/EXC-1/decision-trail")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    g = body["gates"][0]
    assert g["decided_by"] == "u1" and g["decision"] == "approve"
    assert g["sod_satisfied"] is True and g["comment"] == "ok"
    assert g["approved"] == {"artifact_key": "art.x", "schema_ref": "art.x@1.0.0"}


def test_lineage_endpoint():
    reader = FakeReader(
        trace_id="trace-9",
        spans=[
            {"span_id": "s1", "element_id": "A", "artifact_key": "art.a", "schema_ref": "art.a@1.0.0",
             "actor_kind": "capability", "link_span_ids": []},
            {"span_id": "s2", "element_id": "B", "artifact_key": "art.b", "schema_ref": "art.b@1.0.0",
             "actor_kind": "capability", "link_span_ids": ["s1"]},
        ],
        artifacts=[{"artifact_key": "art.a", "authored_by_human": 0},
                   {"artifact_key": "art.b", "authored_by_human": 0}],
    )
    r = _client(reader).get("/audit/instances/EXC-1/lineage")
    assert r.status_code == 200
    body = r.json()
    assert body["trace_id"] == "trace-9"
    assert {n["span_id"] for n in body["nodes"]} == {"s1", "s2"}
    assert body["edges"] == [{"from_span": "s1", "to_span": "s2",
                              "from_artifact_key": "art.a", "to_artifact_key": "art.b"}]


def test_lineage_empty_when_no_trace():
    r = _client(FakeReader(trace_id="")).get("/audit/instances/NONE/lineage")
    assert r.status_code == 200
    body = r.json()
    assert body["trace_id"] == "" and body["nodes"] == [] and body["edges"] == []
