# app/events/rabbit.py
"""aio-pika connection lifecycle + exchange declaration ONLY.

No consumers or publishers yet — the runtime does not process dispatch events in
this slice. This exists so the durable ``amendia.events`` topic exchange is
declared on startup and readiness can be reported.
"""
from __future__ import annotations

import logging

import aio_pika
from aio_pika import ExchangeType

from amendia_common.events import EXCHANGE

logger = logging.getLogger(__name__)


class RabbitConnection:
    def __init__(self, url: str) -> None:
        self._url = url
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None

    async def connect(self) -> None:
        self._connection = await aio_pika.connect_robust(self._url, timeout=15)
        self._channel = await self._connection.channel()
        self._exchange = await self._channel.declare_exchange(
            EXCHANGE, ExchangeType.TOPIC, durable=True
        )
        logger.info("Connected to RabbitMQ, declared durable topic exchange '%s'", EXCHANGE)

    @property
    def is_ready(self) -> bool:
        return self._connection is not None and not self._connection.is_closed

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None
        self._exchange = None
        logger.info("Closed RabbitMQ connection")
