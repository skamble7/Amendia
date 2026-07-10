# app/events/rabbit.py
"""aio-pika consumer: subscribe to exception_raised events on amendia.events.

Declares the canonical durable topic exchange, binds a durable queue with the
``stub_exception.exception_raised.v1`` pattern (built from shared constants),
and dispatches each message to the injected handler. Reconnects with jittered
backoff, mirroring the notification-service pattern.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Awaitable, Callable, Optional

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from amendia_common.events import EXCEPTION_RAISED, EXCHANGE, Service, Version
from app.models.events import IncomingExceptionRaisedEvent

logger = logging.getLogger(__name__)

# Bind to service=stub_exception, event=exception_raised, version=v1.
BINDING_KEY = f"{Service.STUBEXCEPTION.value}.{EXCEPTION_RAISED}.{Version.V1.value}"

Handler = Callable[[IncomingExceptionRaisedEvent, str], Awaitable[None]]


class RabbitConsumer:
    def __init__(self, url: str, queue_name: str, handler: Handler) -> None:
        self._url = url
        self._queue_name = queue_name
        self._handler = handler
        self._stop = asyncio.Event()
        self._connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractChannel] = None
        self._queue: Optional[aio_pika.abc.AbstractQueue] = None

    async def _connect(self) -> None:
        """Connect, declare the exchange/queue, and bind. Retries until stopped."""
        attempt = 0
        while not self._stop.is_set():
            try:
                self._connection = await aio_pika.connect_robust(self._url, timeout=15)
                self._channel = await self._connection.channel()
                await self._channel.set_qos(prefetch_count=16)

                exchange = await self._channel.declare_exchange(
                    EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
                )
                self._queue = await self._channel.declare_queue(self._queue_name, durable=True)
                await self._queue.bind(exchange, routing_key=BINDING_KEY)
                logger.info(
                    "RabbitMQ ready: queue '%s' bound to '%s' with '%s'",
                    self._queue_name, EXCHANGE, BINDING_KEY,
                )
                return
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                wait = min(30, 1 + attempt * 1.5) + random.uniform(0, 0.75)
                logger.warning("RabbitMQ connect failed (attempt %d): %s. Retrying in %.1fs", attempt, exc, wait)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    continue

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        # Catch everything and ack — a bad message must not poison-requeue forever.
        async with message.process(ignore_processed=True):
            try:
                payload = json.loads(message.body.decode("utf-8"))
                event = IncomingExceptionRaisedEvent.model_validate(payload)
            except Exception as exc:  # noqa: BLE001
                logger.error("Dropping unparseable message (routing_key=%s): %s", message.routing_key, exc)
                return
            try:
                await self._handler(event, message.routing_key or "")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Handler error for exception_id=%s: %s", event.exception_id, exc)

    async def run(self) -> None:
        """Consumer main loop; reconnects on failure until stopped."""
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
                logger.exception("Consumer error, will reconnect: %s", exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
        logger.info("Consumer loop stopped")

    @property
    def is_ready(self) -> bool:
        return self._connection is not None and not self._connection.is_closed

    async def stop(self) -> None:
        self._stop.set()
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        logger.info("Consumer stopped")
