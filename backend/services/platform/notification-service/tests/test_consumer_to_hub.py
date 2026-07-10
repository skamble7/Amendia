"""Consumer → hub: a broker message drives a mapped signal into the hub, and a
bad body is dropped without raising."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

from app.events.consumer import BroadcastConsumer
from app.events.signal_mapper import to_signal
from app.hub import NotificationHub


class FakeMessage:
    """Minimal stand-in for aio_pika's AbstractIncomingMessage."""

    def __init__(self, body: bytes, routing_key: str) -> None:
        self.body = body
        self.routing_key = routing_key

    def process(self, ignore_processed: bool = False):
        @asynccontextmanager
        async def _cm():
            yield

        return _cm()


def _make_consumer(hub: NotificationHub) -> BroadcastConsumer:
    async def handle(payload: dict, routing_key: str) -> None:
        sig = to_signal(payload, routing_key)
        if sig is not None:
            hub.publish(sig)

    return BroadcastConsumer("amqp://unused", handle)


async def test_message_becomes_signal_in_hub():
    hub = NotificationHub()
    q = hub.subscribe()
    consumer = _make_consumer(hub)

    body = json.dumps({
        "tenant": "bank-alpha", "task_id": "hitl-1", "process_instance_id": "pi-1",
        "exception_id": "EXC-1", "element_id": "Task_Assess",
        "role": "role.payments.ops_analyst", "decision": "approve",  # must not leak
    }).encode()
    msg = FakeMessage(body, "bank-alpha.agent_runtime.hitl_task_decided.v1")

    await consumer._on_message(msg)

    sig = q.get_nowait()
    assert sig["type"] == "hitl_task_decided"
    assert sig["task_id"] == "hitl-1"
    assert "decision" not in sig


async def test_unparseable_body_is_dropped_without_raising():
    hub = NotificationHub()
    q = hub.subscribe()
    consumer = _make_consumer(hub)

    await consumer._on_message(FakeMessage(b"not json{{", "bank-alpha.agent_runtime.process_completed.v1"))

    assert q.empty()  # nothing published


async def test_irrelevant_event_produces_no_signal():
    hub = NotificationHub()
    q = hub.subscribe()
    consumer = _make_consumer(hub)

    body = json.dumps({"tenant": "t"}).encode()
    await consumer._on_message(FakeMessage(body, "t.agent_runtime.something_else.v1"))

    assert q.empty()
