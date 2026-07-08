# app/events/reply_consumer.py
"""aio-pika consumer for the agent-runtime's dispatch replies.

Binds a durable queue to both ``*.agent_runtime.dispatch_accepted.v1`` and
``*.agent_runtime.dispatch_rejected.v1`` and hands each raw payload + routing key
to the injected handler (the two reply shapes differ, so parsing is the handler's
job). Same reconnect/ack discipline as the exception_raised consumer.
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
    DISPATCH_REJECTED,
    EXCHANGE,
    Service,
    Version,
)

logger = logging.getLogger(__name__)

BINDING_KEYS = [
    f"*.{Service.AGENT_RUNTIME.value}.{DISPATCH_ACCEPTED}.{Version.V1.value}",
    f"*.{Service.AGENT_RUNTIME.value}.{DISPATCH_REJECTED}.{Version.V1.value}",
]

Handler = Callable[[dict, str], Awaitable[None]]


class ReplyConsumer:
    def __init__(self, url: str, queue_name: str, handler: Handler,
                 binding_keys: Optional[List[str]] = None) -> None:
        self._url = url
        self._queue_name = queue_name
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
                await self._channel.set_qos(prefetch_count=16)
                exchange = await self._channel.declare_exchange(
                    EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
                )
                self._queue = await self._channel.declare_queue(self._queue_name, durable=True)
                for key in self._binding_keys:
                    await self._queue.bind(exchange, routing_key=key)
                logger.info("Reply queue '%s' bound to %s", self._queue_name, self._binding_keys)
                return
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                wait = min(30, 1 + attempt * 1.5) + random.uniform(0, 0.75)
                logger.warning("Reply consumer connect failed (attempt %d): %s. Retrying in %.1fs",
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
                logger.error("Dropping unparseable reply (routing_key=%s): %s", message.routing_key, exc)
                return
            try:
                await self._handler(payload, message.routing_key or "")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Reply handler error (routing_key=%s): %s", message.routing_key, exc)

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
                logger.exception("Reply consumer error, will reconnect: %s", exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
        logger.info("Reply consumer loop stopped")

    @property
    def is_ready(self) -> bool:
        return self._connection is not None and not self._connection.is_closed

    async def stop(self) -> None:
        self._stop.set()
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
