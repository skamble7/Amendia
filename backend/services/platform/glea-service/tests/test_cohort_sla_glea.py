# tests/test_cohort_sla_glea.py
"""ADR-064 P3 — GLEA cohort-SLA surfacing: the mapper branch, schema↔insert consistency, requeue discipline,
the current-state/owner-rollup read-model, and the endpoint SLA section + list badges (backward-compatible)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import orjson
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.clickhouse import schema
from app.clickhouse.client import StorageUnavailable
from app.deps import get_cohort_reader
from app.events.consumer import AUDIT_BINDING_KEYS, AuditConsumer
from app.events.mapper import (
    UnmappableEvent, is_cohort_event, is_cohort_sla_event, to_cohort_sla_row,
)
from app.readmodels import build_cohort_detail, build_cohort_list, current_sla_states, sla_summary
from app.routers import cohorts

SLA_RK = "agent_runtime.cohort_sla.v1"
T0 = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)


def _sla_payload(**over):
    p = {
        "event_id": uuid.uuid4().hex,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "state": "breached",
        "cohort_instance_id": "coh-1",
        "cohort_def_id": "ach_cohort",
        "correlation_value": "1v23p",
        "sla_id": "edge:a->b",
        "kind": "edge",
        "ref": "a->b",
        "owner": "external",
        "clock": "wall",
        "due_at": "2026-08-12T12:05:00+00:00",
        "at_risk_at": "2026-08-12T12:03:00+00:00",
        "detected_at": "2026-08-12T12:05:01+00:00",
    }
    p.update(over)
    return p


def _sla_row(sla_id, state, at, *, owner="external", cohort="coh-1", value="1v23p", kind="edge"):
    return {
        "event_id": f"{sla_id}-{state}-{at.isoformat()}", "occurred_at": at, "state": state,
        "cohort_instance_id": cohort, "cohort_def_id": "ach_cohort", "correlation_value": value,
        "sla_id": sla_id, "kind": kind, "ref": sla_id.split(":")[-1], "owner": owner, "clock": "wall",
        "due_at": "", "at_risk_at": "", "detected_at": "",
    }


# --- binding + mapper --------------------------------------------------------------------------------

def test_sla_binding_key_registered_and_disjoint():
    assert SLA_RK in AUDIT_BINDING_KEYS
    assert is_cohort_sla_event(SLA_RK)
    assert not is_cohort_sla_event("agent_runtime.cohort_lifecycle.v1")
    assert not is_cohort_event(SLA_RK)                       # the two cohort tables never overlap


def test_to_cohort_sla_row_maps_payload():
    row = to_cohort_sla_row(SLA_RK, _sla_payload())
    assert row["state"] == "breached" and row["owner"] == "external"
    assert row["sla_id"] == "edge:a->b" and row["kind"] == "edge" and row["ref"] == "a->b"
    assert row["due_at"] == "2026-08-12T12:05:00+00:00" and row["detected_at"] == "2026-08-12T12:05:01+00:00"


def test_to_cohort_sla_row_rejects_missing_ids():
    with pytest.raises(UnmappableEvent):
        to_cohort_sla_row(SLA_RK, {"occurred_at": T0.isoformat()})                       # no event_id
    with pytest.raises(UnmappableEvent):
        to_cohort_sla_row(SLA_RK, {"event_id": "e", "occurred_at": T0.isoformat()})       # no cohort id
    with pytest.raises(UnmappableEvent):
        to_cohort_sla_row(SLA_RK, {"event_id": "e", "occurred_at": T0.isoformat(),
                                   "cohort_instance_id": "c"})                            # no sla_id


def test_sla_row_is_deterministic_for_dedup():
    p = _sla_payload()
    assert to_cohort_sla_row(SLA_RK, p) == to_cohort_sla_row(SLA_RK, dict(p))            # dedup under FINAL


def test_sla_insert_columns_match_table_ddl():
    ddl = schema.create_cohort_sla_table_ddl("glea", "cohort_sla_events", 30)
    body = ddl.split("(", 1)[1]
    cols = set()
    for raw in body.splitlines():
        line = raw.strip().rstrip(",")
        if line.startswith(")"):
            break
        if line and not line.startswith("--"):
            cols.add(line.split()[0])
    assert set(schema.COHORT_SLA_INSERT_COLUMNS) <= cols
    assert set(schema.COHORT_SLA_READ_COLUMNS) <= cols


# --- current-state derivation + owner rollup ---------------------------------------------------------

def test_current_state_latest_event_wins():
    rows = [
        _sla_row("edge:a->b", "at_risk", T0),
        _sla_row("edge:a->b", "breached", T0 + timedelta(minutes=1)),   # later → wins
    ]
    states = current_sla_states(rows)
    assert len(states) == 1 and states[0]["state"] == "breached"


def test_at_risk_then_satisfied_is_satisfied():
    rows = [
        _sla_row("edge:a->b", "at_risk", T0),
        _sla_row("edge:a->b", "satisfied", T0 + timedelta(minutes=1)),
    ]
    assert current_sla_states(rows)[0]["state"] == "satisfied"


def test_owner_rollup_attributes_breaches():
    rows = [
        _sla_row("edge:a->b", "breached", T0, owner="external"),
        _sla_row("node:b", "breached", T0, owner="amendia"),
        _sla_row("e2e", "at_risk", T0, owner="shared"),
        _sla_row("edge:b->c", "satisfied", T0, owner="external"),
        _sla_row("edge:c->d", "voided", T0, owner="external"),
    ]
    s = sla_summary(current_sla_states(rows))
    assert s["breaches"] == {"external": 1, "amendia": 1, "shared": 0, "total": 2}
    assert s["at_risk"] == 1 and s["satisfied"] == 1 and s["voided"] == 1


def test_empty_sla_rows_is_empty_summary():
    s = sla_summary(current_sla_states([]))
    assert s["states"] == [] and s["breaches"]["total"] == 0 and s["at_risk"] == 0


# --- requeue discipline: an SLA insert failing on ClickHouse must NACK+requeue -----------------------

class _FakeMessage:
    def __init__(self, body, routing_key=SLA_RK):
        self.body, self.routing_key = body, routing_key
        self.acked = self.nacked_requeue = self.rejected_requeue = None

    async def ack(self):
        self.acked = True

    async def nack(self, requeue=True):
        self.nacked_requeue = requeue

    async def reject(self, requeue=False):
        self.rejected_requeue = requeue


async def test_sla_storage_unavailable_requeues():
    async def handler(rk, payload):
        assert is_cohort_sla_event(rk)
        raise StorageUnavailable("clickhouse down")

    msg = _FakeMessage(orjson.dumps(_sla_payload()))
    await AuditConsumer("amqp://unused", handler)._on_message(msg)
    assert msg.nacked_requeue is True and msg.acked is None      # kept, not dropped


async def test_sla_unmappable_is_dropped():
    async def handler(rk, payload):
        raise UnmappableEvent("no sla_id")

    msg = _FakeMessage(orjson.dumps({"event_id": "e"}))
    await AuditConsumer("amqp://unused", handler)._on_message(msg)
    assert msg.rejected_requeue is False and msg.acked is None   # poison → dropped, not requeued


# --- read-model wiring into detail/list --------------------------------------------------------------

def _cev(op, at, cohort="coh-1", value="1v23p", **over):
    row = {"event_id": f"{op}-{cohort}-{at.isoformat()}", "occurred_at": at, "op": op,
           "cohort_instance_id": cohort, "cohort_def_id": "ach_cohort", "correlation_value": value,
           "member_process_instance_id": "", "member_pack_key": "", "member_pack_version": "",
           "member_correlation_id": "", "close_outcome": "", "detail": "", "trace_id": ""}
    row.update(over)
    return row


def test_detail_carries_sla_section():
    cohort_rows = [_cev("opened", T0)]
    sla_rows = [
        _sla_row("edge:a->b", "breached", T0 + timedelta(minutes=1), owner="external"),
        _sla_row("node:b", "at_risk", T0 + timedelta(minutes=1), owner="amendia"),
    ]
    detail = build_cohort_detail(cohort_rows, [], sla_rows)
    assert detail["sla"]["breaches"] == {"external": 1, "amendia": 0, "shared": 0, "total": 1}
    assert detail["sla"]["at_risk"] == 1
    assert {e["sla_id"] for e in detail["sla"]["states"]} == {"edge:a->b", "node:b"}


def test_detail_without_sla_events_is_empty_backward_compatible():
    detail = build_cohort_detail([_cev("opened", T0)], [], [])
    assert detail["sla"]["states"] == [] and detail["sla"]["breaches"]["total"] == 0


def test_list_carries_compact_sla_badges():
    cohort_rows = [_cev("opened", T0, cohort="coh-1"), _cev("opened", T0, cohort="coh-2")]
    sla_rows = [
        _sla_row("edge:a->b", "breached", T0, cohort="coh-1"),
        _sla_row("node:b", "at_risk", T0, cohort="coh-1"),
    ]
    lst = build_cohort_list(cohort_rows, [], sla_rows)
    by_id = {c["cohort_instance_id"]: c for c in lst}
    assert by_id["coh-1"]["sla_breaches"] == 1 and by_id["coh-1"]["sla_at_risk"] == 1
    assert by_id["coh-2"]["sla_breaches"] == 0 and by_id["coh-2"]["sla_at_risk"] == 0   # no SLA → zero badges


# --- endpoint: detail SLA section over a fake reader --------------------------------------------------

class _FakeReader:
    def __init__(self, cohort_rows, sla_rows):
        self._c, self._s = cohort_rows, sla_rows

    async def cohort_events_all(self):
        return list(self._c)

    async def cohort_events_for(self, cid):
        return [r for r in self._c if r["cohort_instance_id"] == cid]

    async def cohort_events_by_correlation_value(self, v):
        return [r for r in self._c if r["correlation_value"] == v]

    async def member_outcomes(self, cids):
        return []

    async def cohort_sla_events_all(self):
        return list(self._s)

    async def cohort_sla_events_for(self, cid):
        return [r for r in self._s if r["cohort_instance_id"] == cid]

    async def cohort_sla_events_by_correlation_value(self, v):
        return [r for r in self._s if r["correlation_value"] == v]


def _client(reader):
    app = FastAPI()
    app.include_router(cohorts.router)
    app.dependency_overrides[get_cohort_reader] = lambda: reader
    return TestClient(app)


def test_detail_endpoint_returns_sla_section():
    reader = _FakeReader([_cev("opened", T0)],
                         [_sla_row("edge:a->b", "breached", T0 + timedelta(minutes=1), owner="external")])
    body = _client(reader).get("/cohorts/coh-1").json()
    assert body["sla"]["breaches"]["external"] == 1 and body["sla"]["breaches"]["total"] == 1
    assert body["sla"]["states"][0]["sla_id"] == "edge:a->b"


def test_list_endpoint_returns_badges_and_detail_empty_when_no_sla():
    reader = _FakeReader([_cev("opened", T0, cohort="coh-1")], [])
    listing = _client(reader).get("/cohorts").json()
    assert listing["cohorts"][0]["sla_breaches"] == 0 and listing["cohorts"][0]["sla_at_risk"] == 0
    detail = _client(reader).get("/cohorts/coh-1").json()
    assert detail["sla"]["states"] == []                    # backward-compatible empty shape
