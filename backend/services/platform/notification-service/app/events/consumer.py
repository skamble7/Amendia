# app/events/consumer.py
"""Broadcast consumer for the notification-service.

Adapted from ``ingestor/app/events/reply_consumer.py`` (same connect/backoff loop
and ack discipline), with ONE deliberate divergence that is the whole point of this
service:

    self._queue = await channel.declare_queue("", exclusive=True, auto_delete=True)

Every OTHER consumer in the platform uses a durable, *named* queue — work-queue /
competing-consumers semantics, where replicas of a service split the messages. Here
we want the opposite: **each notification-service process must receive EVERY matching
event** so it can fan out to its own connected browsers. A server-named, exclusive,
auto-delete queue gives that broadcast behaviour (and is torn down when the process
disconnects). Do NOT change this to a durable named queue — replicas would then
round-robin events and browsers would miss half of them.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Awaitable, Callable, List, Optional

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from amendia_common.events import (
    DISPATCH_ACCEPTED,
    EXCEPTION_DISPATCHED,
    EXCEPTION_RAISED,
    EXCHANGE,
    HITL_TASK_CREATED,
    HITL_TASK_DECIDED,
    PROCESS_COMPLETED,
    PROCESS_FAILED,
    Service,
    Version,
)

logger = logging.getLogger(__name__)

_V1 = Version.V1.value
BINDING_KEYS: List[str] = [
    f"{Service.AGENT_RUNTIME.value}.{HITL_TASK_CREATED}.{_V1}",
    f"{Service.AGENT_RUNTIME.value}.{HITL_TASK_DECIDED}.{_V1}",
    f"{Service.AGENT_RUNTIME.value}.{PROCESS_COMPLETED}.{_V1}",
    f"{Service.AGENT_RUNTIME.value}.{PROCESS_FAILED}.{_V1}",
    f"{Service.AGENT_RUNTIME.value}.{DISPATCH_ACCEPTED}.{_V1}",
    f"{Service.INGESTOR.value}.{EXCEPTION_DISPATCHED}.{_V1}",
    f"{Service.STUBEXCEPTION.value}.{EXCEPTION_RAISED}.{_V1}",
]

Handler = Callable[[dict, str], Awaitable[None]]


class BroadcastConsumer:
    def __init__(self, url: str, handler: Handler,
                 binding_keys: Optional[List[str]] = None) -> None:
        self._url = url
        self._handler = handler
        self._binding_keys = binding_keys or BINDING_KEYS
        self._stop = asyncio.Event()
        self._connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractChannel] = None
        self._queue: Optional[aio_pika.abc.AbstractQueue] = None

    async def _connect(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                self._connection = await aio_pika.connect_robust(self._url, timeout=15)
                self._channel = await self._connection.channel()
                await self._channel.set_qos(prefetch_count=32)
                exchange = await self._channel.declare_exchange(
                    EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
                )
                # Broadcast queue: server-named, exclusive, auto-deleted on disconnect.
                self._queue = await self._channel.declare_queue(
                    "", exclusive=True, auto_delete=True
                )
                for key in self._binding_keys:
                    await self._queue.bind(exchange, routing_key=key)
                logger.info("Broadcast queue '%s' bound to %s",
                            self._queue.name, self._binding_keys)
                return
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                wait = min(30, 1 + attempt * 1.5) + random.uniform(0, 0.75)
                logger.warning("Notification consumer connect failed (attempt %d): %s. "
                               "Retrying in %.1fs", attempt, exc, wait)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    continue

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        async with message.process(ignore_processed=True):
            try:
                payload = json.loads(message.body.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.error("Dropping unparseable event (routing_key=%s): %s",
                             message.routing_key, exc)
                return
            try:
                await self._handler(payload, message.routing_key or "")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Notification handler error (routing_key=%s): %s",
                                 message.routing_key, exc)

    async def run(self) -> None:
        self._stop.clear()
        while not self._stop.is_set():
            await self._connect()
            if self._stop.is_set():
                break
            try:
                assert self._queue is not None
                await self._queue.consume(self._on_message, no_ack=False)
                await self._stop.wait()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Notification consumer error, will reconnect: %s", exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
        logger.info("Notification consumer loop stopped")

    @property
    def is_ready(self) -> bool:
        return self._connection is not None and not self._connection.is_closed

    async def stop(self) -> None:
        self._stop.set()
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
