# app/events/rabbit.py
"""aio-pika connection/channel lifecycle, exchange declaration, publish helper.

Declares the canonical Amendia topic exchange (``amendia.events``) and publishes
thin exception-raised events with persistent delivery and publisher confirms.
"""
from __future__ import annotations

import json
import logging

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message

from amendia_common.events import EXCHANGE

logger = logging.getLogger(__name__)


class RabbitPublisher:
    """Owns a robust connection + confirming channel + the events exchange."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None

    async def connect(self) -> None:
        self._connection = await aio_pika.connect_robust(self._url, timeout=15)
        # publisher_confirms=True (the default) makes publish() await broker ack.
        self._channel = await self._connection.channel(publisher_confirms=True)
        self._exchange = await self._channel.declare_exchange(
            EXCHANGE, ExchangeType.TOPIC, durable=True
        )
        logger.info("Connected to RabbitMQ, declared durable topic exchange '%s'", EXCHANGE)

    async def publish(self, event: dict, routing_key: str, message_id: str) -> None:
        """Publish a JSON event. Raises on failure (no broker ack)."""
        if self._exchange is None:
            raise RuntimeError("RabbitPublisher not connected")

        message = Message(
            body=json.dumps(event, default=str).encode("utf-8"),
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=message_id,
        )
        await self._exchange.publish(message, routing_key=routing_key)
        logger.info("Published event id=%s routing_key=%s", message_id, routing_key)

    @property
    def is_ready(self) -> bool:
        return (
            self._connection is not None
            and not self._connection.is_closed
            and self._exchange is not None
        )

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
            logger.info("Closed RabbitMQ connection")
        self._connection = None
        self._channel = None
        self._exchange = None
