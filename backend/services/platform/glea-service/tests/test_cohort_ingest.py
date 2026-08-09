# tests/test_cohort_ingest.py
"""ADR-063 Phase 3A — GLEA cohort ingest: the mapper branch, the schema↔insert consistency, and the
requeue-not-drop discipline for the cohort writer on a ClickHouse outage."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import orjson
import pytest

from app.clickhouse import schema
from app.clickhouse.client import StorageUnavailable
from app.events.consumer import AUDIT_BINDING_KEYS, AuditConsumer
from app.events.mapper import UnmappableEvent, is_cohort_event, to_cohort_row

COHORT_RK = "agent_runtime.cohort_lifecycle.v1"


def _member_joined_payload(**over):
    p = {
        "event_id": uuid.uuid4().hex,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "op": "member_joined",
        "cohort_instance_id": "coh-1",
        "cohort_def_id": "wire_transfer_cohort",
        "correlation_value": "1v23p",
        "process_instance_id": "pi-a",
        "pack_key": "wire-repair-standard",
        "pack_version": "1.0.0",
        "trace": {"correlation_id": "cid-a", "trace_id": ""},
    }
    p.update(over)
    return p


def test_cohort_binding_key_registered():
    assert COHORT_RK in AUDIT_BINDING_KEYS
    assert is_cohort_event(COHORT_RK) and not is_cohort_event("agent_runtime.process_completed.v1")


def test_to_cohort_row_maps_member_joined():
    row = to_cohort_row(COHORT_RK, _member_joined_payload())
    assert row["op"] == "member_joined"
    assert row["cohort_instance_id"] == "coh-1"
    assert row["member_process_instance_id"] == "pi-a"
    assert row["member_pack_version"] == "1.0.0"
    assert row["member_correlation_id"] == "cid-a"      # the member's correlation_id (join key)


def test_to_cohort_row_maps_opened_and_closed():
    opened = to_cohort_row(COHORT_RK, _member_joined_payload(op="opened", process_instance_id="", pack_key="",
                                                             pack_version="", trace={}))
    assert opened["op"] == "opened" and opened["member_correlation_id"] == ""
    closed = to_cohort_row(COHORT_RK, _member_joined_payload(op="closed", close_outcome="process_ended",
                                                             process_instance_id="", trace={}))
    assert closed["op"] == "closed" and closed["close_outcome"] == "process_ended"


def test_to_cohort_row_rejects_missing_ids():
    with pytest.raises(UnmappableEvent):
        to_cohort_row(COHORT_RK, {"occurred_at": "2026-08-08T00:00:00+00:00"})           # no event_id
    with pytest.raises(UnmappableEvent):
        to_cohort_row(COHORT_RK, {"event_id": "e", "occurred_at": "2026-08-08T00:00:00+00:00"})  # no cohort id


def test_cohort_row_is_deterministic_for_dedup():
    # Same event_id → identical row → ReplacingMergeTree collapses the redelivery (dedup under FINAL).
    p = _member_joined_payload()
    assert to_cohort_row(COHORT_RK, p) == to_cohort_row(COHORT_RK, dict(p))


def test_cohort_insert_columns_match_table_ddl():
    ddl = schema.create_cohort_table_ddl("glea", "cohort_events", 30)
    body = ddl.split("(", 1)[1]
    cols = set()
    for raw in body.splitlines():
        line = raw.strip().rstrip(",")
        if line.startswith(")"):
            break
        if line and not line.startswith("--"):
            cols.add(line.split()[0])
    assert set(schema.COHORT_INSERT_COLUMNS) <= cols
    assert set(schema.COHORT_READ_COLUMNS) <= cols


# --- requeue discipline: a cohort insert failing on ClickHouse must NACK+requeue (never ack-and-drop) ---
class _FakeMessage:
    def __init__(self, body, routing_key=COHORT_RK):
        self.body, self.routing_key = body, routing_key
        self.acked = self.nacked_requeue = self.rejected_requeue = None

    async def ack(self):
        self.acked = True

    async def nack(self, requeue=True):
        self.nacked_requeue = requeue

    async def reject(self, requeue=False):
        self.rejected_requeue = requeue


async def test_cohort_storage_unavailable_requeues():
    async def handler(rk, payload):
        # mirrors main.handle's cohort branch: a failed cohort insert raises StorageUnavailable
        assert is_cohort_event(rk)
        raise StorageUnavailable("clickhouse down")

    msg = _FakeMessage(orjson.dumps(_member_joined_payload()))
    await AuditConsumer("amqp://unused", handler)._on_message(msg)
    assert msg.nacked_requeue is True and msg.acked is None       # kept, not dropped
