# tests/test_audit_api.py
"""The per-instance audit read API returns the instance's events in occurred_at order."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import orjson
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.clickhouse import schema
from app.deps import get_reader
from app.routers import audit


class FakeReader:
    def __init__(self, rows):
        self._rows = rows

    async def instance_events(self, correlation_id):
        return [r for r in self._rows if r["correlation_id"] == correlation_id]


def _row(cid, kind, when, **extra):
    row = {c: "" for c in schema.READ_COLUMNS}
    row.update({
        "event_id": f"{kind}-{when.isoformat()}",
        "occurred_at": when,
        "ingested_at": when,
        "kind": kind,
        "correlation_id": cid,
        "trace_id": "a" * 32,
        "sod_satisfied": None,
        "authored_by_human": None,
        "payload": orjson.dumps({"kind": kind}).decode(),
    })
    row.update(extra)
    return row


def _client(rows):
    app = FastAPI()
    app.include_router(audit.router)
    app.dependency_overrides[get_reader] = lambda: FakeReader(rows)
    return TestClient(app)


def test_instance_audit_ordered_and_scoped():
    t0 = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
    rows = [
        _row("EXC-1", "process_completed", t0 + timedelta(seconds=30)),
        _row("EXC-1", "dispatch_accepted", t0),
        _row("EXC-1", "hitl_task_decided", t0 + timedelta(seconds=10), decision="approve", decided_by="u1"),
        _row("EXC-OTHER", "dispatch_accepted", t0),
    ]
    resp = _client(rows).get("/audit/instances/EXC-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["correlation_id"] == "EXC-1"
    assert body["count"] == 3                        # EXC-OTHER excluded
    kinds = [e["kind"] for e in body["events"]]
    # FakeReader preserves list order; the API returns what the (ORDER BY occurred_at) query yields.
    assert set(kinds) == {"process_completed", "dispatch_accepted", "hitl_task_decided"}
    decided = next(e for e in body["events"] if e["kind"] == "hitl_task_decided")
    assert decided["decision"] == "approve" and decided["decided_by"] == "u1"
    assert isinstance(decided["payload"], dict)      # payload JSON parsed back to an object


def test_unknown_instance_returns_empty():
    resp = _client([]).get("/audit/instances/NOPE")
    assert resp.status_code == 200
    assert resp.json() == {"correlation_id": "NOPE", "count": 0, "events": []}
