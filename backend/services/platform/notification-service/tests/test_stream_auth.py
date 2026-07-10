"""SSE endpoint: auth-gated (via the HTTP client), and the stream generator delivers
published signals (tested directly — an infinite stream over the ASGI test transport
is unreliable)."""
from __future__ import annotations

import asyncio
import json

from app.hub import NotificationHub
from app.routers.stream import sse_stream


async def test_stream_requires_bearer(client):
    ac, _hub, _app = client
    r = await ac.get("/stream")
    assert r.status_code == 401


async def test_health_reports_readiness(client):
    ac, _hub, _app = client
    r = await ac.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["ready"] is True
    assert body["subscribers"] == 0


async def test_sse_stream_yields_ready_then_published_signal():
    hub = NotificationHub()
    disconnected = asyncio.Event()

    async def is_disconnected() -> bool:
        return disconnected.is_set()

    gen = sse_stream(hub, is_disconnected, heartbeat_seconds=20)
    try:
        # First frame is the ready event — subscription is active by now.
        ready = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert ready.startswith("event: ready")
        assert hub.subscriber_count == 1

        hub.publish({"type": "hitl_task_created", "task_id": "hitl-1", "process_instance_id": "pi-1"})
        frame = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert frame.startswith("data: ")
        payload = json.loads(frame[len("data: "):].strip())
        assert payload == {"type": "hitl_task_created", "task_id": "hitl-1", "process_instance_id": "pi-1"}
    finally:
        disconnected.set()
        await gen.aclose()

    # The generator cleaned up its subscription.
    assert hub.subscriber_count == 0


async def test_sse_stream_emits_heartbeat_when_idle():
    hub = NotificationHub()

    async def is_disconnected() -> bool:
        return False

    gen = sse_stream(hub, is_disconnected, heartbeat_seconds=0)  # immediate timeout → ping
    try:
        ready = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert ready.startswith("event: ready")
        ping = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert ping.startswith(": ping")
    finally:
        await gen.aclose()
