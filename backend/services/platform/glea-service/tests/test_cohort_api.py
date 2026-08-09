# tests/test_cohort_api.py
"""ADR-063 Phase 3A — the cohort read API returns list / detail / by-correlation shapes; 404 on unknown."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_cohort_reader
from app.routers import cohorts

T0 = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)


def _cev(op, at, cohort, value, **over):
    row = {"event_id": f"{op}-{cohort}-{at.isoformat()}", "occurred_at": at, "op": op,
           "cohort_instance_id": cohort, "cohort_def_id": "wtc", "correlation_value": value,
           "member_process_instance_id": "", "member_pack_key": "", "member_pack_version": "",
           "member_correlation_id": "", "close_outcome": "", "detail": "", "trace_id": ""}
    row.update(over)
    return row


_ROWS = [
    _cev("opened", T0, "coh-1", "1v23p"),
    _cev("member_joined", T0 + timedelta(seconds=1), "coh-1", "1v23p",
         member_process_instance_id="pi-a", member_pack_key="p", member_pack_version="1.0.0",
         member_correlation_id="cid-a"),
    _cev("closed", T0 + timedelta(seconds=30), "coh-1", "1v23p", close_outcome="process_ended"),
    _cev("opened", T0 + timedelta(hours=1), "coh-2", "9z88q"),
]
_OUTCOMES = [
    {"correlation_id": "cid-a", "kind": "dispatch_accepted", "occurred_at": T0 + timedelta(seconds=1), "outcome": ""},
    {"correlation_id": "cid-a", "kind": "process_completed", "occurred_at": T0 + timedelta(seconds=20),
     "outcome": "End_Resolved"},
]


class FakeCohortReader:
    async def cohort_events_all(self):
        return list(_ROWS)

    async def cohort_events_for(self, cohort_instance_id):
        return [r for r in _ROWS if r["cohort_instance_id"] == cohort_instance_id]

    async def cohort_events_by_correlation_value(self, correlation_value):
        return [r for r in _ROWS if r["correlation_value"] == correlation_value]

    async def member_outcomes(self, correlation_ids):
        return [o for o in _OUTCOMES if o["correlation_id"] in set(correlation_ids)]


def _client():
    app = FastAPI()
    app.include_router(cohorts.router)
    app.dependency_overrides[get_cohort_reader] = lambda: FakeCohortReader()
    return TestClient(app)


def test_list_cohorts_newest_first_with_rollup():
    body = _client().get("/cohorts").json()
    assert body["count"] == 2
    assert [c["cohort_instance_id"] for c in body["cohorts"]] == ["coh-2", "coh-1"]  # newest opened first
    coh1 = next(c for c in body["cohorts"] if c["cohort_instance_id"] == "coh-1")
    assert coh1["state"] == "closed" and coh1["outcome"] == "process_ended"
    assert coh1["member_count"] == 1 and coh1["rollup"] == {"done": 1, "running": 0, "failed": 0}


def test_list_state_filter():
    body = _client().get("/cohorts", params={"state": "closed"}).json()
    assert [c["cohort_instance_id"] for c in body["cohorts"]] == ["coh-1"]


def test_cohort_detail_shape():
    body = _client().get("/cohorts/coh-1").json()
    assert body["cohort_instance_id"] == "coh-1"
    assert body["close"]["signalled"] is True and body["close"]["outcome"] == "process_ended"
    assert len(body["roster"]) == 1 and body["roster"][0]["status"] == "done"
    assert [e["op"] for e in body["events"]] == ["opened", "member_joined", "closed"]


def test_cohort_by_correlation():
    body = _client().get("/cohorts/by-correlation/1v23p").json()
    assert body["cohort_instance_id"] == "coh-1" and body["correlation_value"] == "1v23p"


def test_unknown_id_and_value_are_404():
    assert _client().get("/cohorts/nope").status_code == 404
    assert _client().get("/cohorts/by-correlation/nope").status_code == 404
