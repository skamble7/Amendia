# app/events/consumer.py
"""aio-pika consumer for inbound ``exception_dispatched`` events.

Binds a durable queue to ``ingestor.exception_dispatched.v1`` and hands each raw
payload + routing key to the injected handler. Same reconnect/ack discipline as
the ingestor's consumer (a bad message is logged + acked, never poison-requeued).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Awaitable, Callable, Optional

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from amendia_common.events import EXCEPTION_DISPATCHED, EXCHANGE, Service, Version

logger = logging.getLogger(__name__)

BINDING_KEY = f"{Service.INGESTOR.value}.{EXCEPTION_DISPATCHED}.{Version.V1.value}"

Handler = Callable[[dict, str], Awaitable[None]]


class DispatchConsumer:
    def __init__(self, url: str, queue_name: str, handler: Handler) -> None:
        self._url = url
        self._queue_name = queue_name
        self._handler = handler
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
                await self._channel.set_qos(prefetch_count=8)
                exchange = await self._channel.declare_exchange(
                    EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
                )
                self._queue = await self._channel.declare_queue(self._queue_name, durable=True)
                await self._queue.bind(exchange, routing_key=BINDING_KEY)
                logger.info("Dispatch queue '%s' bound to '%s'", self._queue_name, BINDING_KEY)
                return
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                wait = min(30, 1 + attempt * 1.5) + random.uniform(0, 0.75)
                logger.warning("Dispatch consumer connect failed (attempt %d): %s. Retry in %.1fs",
                               attempt, exc, wait)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    continue

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        async with message.process(ignore_processed=True):
            try:
                payload = json.loads(message.body.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.error("Dropping unparseable dispatch (rk=%s): %s", message.routing_key, exc)
                return
            try:
                await self._handler(payload, message.routing_key or "")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Dispatch handler error (rk=%s): %s", message.routing_key, exc)

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
                logger.exception("Dispatch consumer error, will reconnect: %s", exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
        logger.info("Dispatch consumer loop stopped")

    @property
    def is_ready(self) -> bool:
        return self._connection is not None and not self._connection.is_closed

    async def stop(self) -> None:
        self._stop.set()
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
