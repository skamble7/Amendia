# tests/test_metrics.py
"""ADR-058 Phase D — the aggregate tiles: pure bundle shaping + the two endpoints (fake reader)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_reader
from app.readmodels import build_metrics
from app.routers import audit


# --- pure assembly ---------------------------------------------------------- #
def test_build_metrics_shapes_full_bundle():
    inputs = {
        "latency": {"p50": 1200.0, "p95": 9000.0, "count": 3},
        "duration": {"p50": 12.5, "p95": 40.0, "count": 5},
        "decisions": [{"decision": "approve", "role": "role.ops.analyst", "count": 2},
                      {"decision": "reject", "role": "role.ops.analyst", "count": 1}],
        "four_eyes": 2, "egress_denied": 1, "sla_breaches": 0,
    }
    b = build_metrics(inputs)
    assert b["approval_latency_ms"] == {"p50": 1200.0, "p95": 9000.0, "count": 3}
    assert b["capability_duration_ms"] == {"p50": 12.5, "p95": 40.0, "count": 5}
    assert b["hitl_decisions"][0] == {"decision": "approve", "role": "role.ops.analyst", "count": 2}
    assert b["four_eyes_enforced"] == 2 and b["egress_denied"] == 1 and b["sla_breaches"] == 0
    assert "instances_by_outcome" not in b            # per-instance bundle omits it


def test_build_metrics_zeroes_empty_instance():
    b = build_metrics({})                              # nothing persisted → all zero, never an error
    assert b["approval_latency_ms"] == {"p50": 0.0, "p95": 0.0, "count": 0}
    assert b["capability_duration_ms"] == {"p50": 0.0, "p95": 0.0, "count": 0}
    assert b["hitl_decisions"] == []
    assert b["four_eyes_enforced"] == 0 and b["egress_denied"] == 0 and b["sla_breaches"] == 0


def test_build_metrics_includes_outcome_when_platform_wide():
    b = build_metrics({"outcome": {"completed": 7, "failed": 2}})
    assert b["instances_by_outcome"] == {"completed": 7, "failed": 2}


# --- endpoints -------------------------------------------------------------- #
class FakeReader:
    def __init__(self, inputs):
        self._inputs = inputs
        self.calls = []

    async def metrics_inputs(self, *, correlation_id=None, since=None, until=None):
        self.calls.append({"correlation_id": correlation_id, "since": since, "until": until})
        return self._inputs


def _client(reader):
    app = FastAPI()
    app.include_router(audit.router)
    app.dependency_overrides[get_reader] = lambda: reader
    return TestClient(app)


def test_instance_metrics_endpoint_scopes_by_correlation_id():
    reader = FakeReader({
        "latency": {"p50": 500.0, "p95": 800.0, "count": 2},
        "duration": {"p50": 3.0, "p95": 9.0, "count": 4},
        "decisions": [{"decision": "approve", "role": "role.ops.approver", "count": 1}],
        "four_eyes": 1, "egress_denied": 0, "sla_breaches": 1,
    })
    r = _client(reader).get("/audit/instances/EXC-1/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["correlation_id"] == "EXC-1"
    assert body["approval_latency_ms"]["p95"] == 800.0
    assert body["sla_breaches"] == 1
    assert body["instances_by_outcome"] is None
    assert reader.calls[0]["correlation_id"] == "EXC-1"   # scoped by correlation_id


def test_platform_metrics_endpoint_uses_window_and_outcome():
    reader = FakeReader({
        "latency": {"p50": 0.0, "p95": 0.0, "count": 0},
        "duration": {"p50": 0.0, "p95": 0.0, "count": 0},
        "decisions": [], "four_eyes": 5, "egress_denied": 3, "sla_breaches": 2,
        "outcome": {"completed": 10, "failed": 4},
    })
    r = _client(reader).get("/audit/metrics", params={"since": "2026-08-01T00:00:00+00:00"})
    assert r.status_code == 200
    body = r.json()
    assert body["correlation_id"] is None
    assert body["instances_by_outcome"] == {"completed": 10, "failed": 4}
    assert body["four_eyes_enforced"] == 5 and body["egress_denied"] == 3
    # platform-wide: no correlation_id predicate, a window IS passed (same builder, predicate dropped).
    call = reader.calls[0]
    assert call["correlation_id"] is None and call["since"] is not None and call["until"] is not None


def test_platform_metrics_defaults_window_when_absent():
    reader = FakeReader({"outcome": {"completed": 0, "failed": 0}})
    r = _client(reader).get("/audit/metrics")
    assert r.status_code == 200
    call = reader.calls[0]
    assert call["since"] is not None and call["until"] is not None   # defaulted (30d window)
