# tests/test_consumer_ack.py
"""The consumer's ack discipline is the no-loss guarantee (ADR-058 Phase B):
  * unparseable body / unmappable event → reject(requeue=False) (drop, never poison-requeue),
  * ClickHouse unavailable              → nack(requeue=True)   (KEEP — never ack-and-drop),
  * success                             → ack().
Plus: idempotency — the same event_id maps to the same ReplacingMergeTree dedupe key, so a requeue →
redelivery collapses to one row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import orjson
import pytest

from app.clickhouse.client import StorageUnavailable
from app.events.consumer import AUDIT_BINDING_KEYS, AuditConsumer
from app.events.mapper import UnmappableEvent, to_row


class FakeMessage:
    def __init__(self, body: bytes, routing_key: str = "agent_runtime.process_completed.v1"):
        self.body = body
        self.routing_key = routing_key
        self.acked = False
        self.nacked_requeue = None
        self.rejected_requeue = None

    async def ack(self):
        self.acked = True

    async def nack(self, requeue: bool = True):
        self.nacked_requeue = requeue

    async def reject(self, requeue: bool = False):
        self.rejected_requeue = requeue


def _consumer(handler):
    return AuditConsumer("amqp://unused", handler)


def _good_body():
    return orjson.dumps({
        "event_id": uuid.uuid4().hex,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "trace": {"correlation_id": "EXC-1", "trace_id": "a" * 32},
    })


async def test_success_acks():
    seen = []

    async def handler(rk, payload):
        seen.append((rk, payload))

    msg = FakeMessage(_good_body())
    await _consumer(handler)._on_message(msg)
    assert msg.acked and msg.nacked_requeue is None and msg.rejected_requeue is None
    assert len(seen) == 1


async def test_clickhouse_down_nacks_with_requeue():
    async def handler(rk, payload):
        raise StorageUnavailable("clickhouse down")

    msg = FakeMessage(_good_body())
    await _consumer(handler)._on_message(msg)
    assert msg.nacked_requeue is True       # KEEP the event
    assert not msg.acked and msg.rejected_requeue is None


async def test_unparseable_body_is_rejected_not_requeued():
    async def handler(rk, payload):  # never called
        raise AssertionError

    msg = FakeMessage(b"not json {{{")
    await _consumer(handler)._on_message(msg)
    assert msg.rejected_requeue is False
    assert not msg.acked and msg.nacked_requeue is None


async def test_unmappable_event_is_rejected_not_requeued():
    async def handler(rk, payload):
        raise UnmappableEvent("no event_id")

    msg = FakeMessage(orjson.dumps({"foo": "bar"}))
    await _consumer(handler)._on_message(msg)
    assert msg.rejected_requeue is False
    assert not msg.acked and msg.nacked_requeue is None


async def test_poison_logic_error_is_rejected_not_requeued():
    async def handler(rk, payload):
        raise ValueError("bad row")

    msg = FakeMessage(_good_body())
    await _consumer(handler)._on_message(msg)
    assert msg.rejected_requeue is False and not msg.acked


def test_redelivered_event_id_is_the_same_dedupe_key():
    # A requeue redelivers the identical body → identical event_id → identical ReplacingMergeTree
    # ORDER BY tuple (correlation_id, occurred_at, event_id) → collapses to one row.
    body = _good_body()
    payload = orjson.loads(body)
    r1 = to_row("agent_runtime.process_completed.v1", payload)
    r2 = to_row("agent_runtime.process_completed.v1", payload)
    assert (r1["correlation_id"], r1["occurred_at"], r1["event_id"]) == \
           (r2["correlation_id"], r2["occurred_at"], r2["event_id"])


def test_audit_binding_covers_governed_events():
    keys = set(AUDIT_BINDING_KEYS)
    for expected in ("agent_runtime.hitl_task_decided.v1", "agent_runtime.egress_decision.v1",
                     "agent_runtime.artifact_committed.v1", "identity.role_changed.v1",
                     "process_registry.pack_lifecycle.v1"):
        assert expected in keys
