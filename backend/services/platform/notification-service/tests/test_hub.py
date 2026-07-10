"""Fan-out hub: broadcast to all subscribers, unsubscribe, and slow-client collapse."""
from __future__ import annotations

import asyncio

from app.hub import RESYNC_SIGNAL, NotificationHub


async def test_publish_fans_out_to_all_subscribers():
    hub = NotificationHub()
    a = hub.subscribe()
    b = hub.subscribe()
    assert hub.subscriber_count == 2

    hub.publish({"type": "hitl_task_created", "task_id": "t1"})

    assert (await a.get())["task_id"] == "t1"
    assert (await b.get())["task_id"] == "t1"


async def test_unsubscribe_stops_delivery():
    hub = NotificationHub()
    q = hub.subscribe()
    hub.unsubscribe(q)
    assert hub.subscriber_count == 0

    hub.publish({"type": "x"})
    assert q.empty()


async def test_slow_client_backlog_collapses_to_resync():
    hub = NotificationHub(client_queue_maxsize=2)
    q = hub.subscribe()

    hub.publish({"type": "a"})
    hub.publish({"type": "b"})  # queue now full (2)
    hub.publish({"type": "c"})  # overflow → collapse

    # The backlog is replaced by a single resync signal.
    assert q.qsize() == 1
    assert q.get_nowait() == RESYNC_SIGNAL
    assert q.empty()


async def test_publish_never_blocks_on_full_queue():
    hub = NotificationHub(client_queue_maxsize=1)
    hub.subscribe()
    # Many publishes against a full queue must not raise or await.
    for i in range(50):
        hub.publish({"type": "e", "n": i})
    assert True  # reached here without hanging/raising


async def test_await_get_receives_next_signal():
    hub = NotificationHub()
    q = hub.subscribe()

    async def publish_soon():
        await asyncio.sleep(0.01)
        hub.publish({"type": "process_completed", "process_instance_id": "pi-9"})

    asyncio.create_task(publish_soon())
    sig = await asyncio.wait_for(q.get(), timeout=1.0)
    assert sig["process_instance_id"] == "pi-9"
