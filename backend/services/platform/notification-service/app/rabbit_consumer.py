# app/rabbit_consumer.py
from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone
from typing import List, Optional

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from app.settings import settings
from app.websocket_manager import websocket_manager
from app.logger import logger


_stop_event = asyncio.Event()
_connection: Optional[aio_pika.RobustConnection] = None
_channel: Optional[aio_pika.abc.AbstractChannel] = None
_queue: Optional[aio_pika.abc.AbstractQueue] = None


def _exchange_type() -> aio_pika.ExchangeType:
    et = (settings.RABBITMQ_EXCHANGE_TYPE or "topic").lower()
    if et == "direct":
        return aio_pika.ExchangeType.DIRECT
    if et == "fanout":
        return aio_pika.ExchangeType.FANOUT
    if et == "headers":
        return aio_pika.ExchangeType.HEADERS
    return aio_pika.ExchangeType.TOPIC


async def _ensure_connected() -> None:
    """
    Connect to RabbitMQ, declare exchange/queue, and bind routing keys.
    Retries with jittered backoff until successful or stop is signaled.
    """
    global _connection, _channel, _queue

    attempt = 0
    while not _stop_event.is_set():
        try:
            logger.info("Connecting to RabbitMQ ...")
            _connection = await aio_pika.connect_robust(
                settings.RABBITMQ_URL,
                timeout=15,
                client_properties={"connection_name": settings.SERVICE_NAME},
            )
            _channel = await _connection.channel()
            await _channel.set_qos(prefetch_count=64)

            exchange = await _channel.declare_exchange(
                settings.RABBITMQ_EXCHANGE,
                _exchange_type(),
                durable=True,
            )

            queue_name = settings.RABBITMQ_QUEUE or ""
            _queue = await _channel.declare_queue(
                queue_name,
                durable=True if queue_name else False,
                auto_delete=False if queue_name else True,  # temp queue if no name
            )

            bindings: List[str] = settings.RABBITMQ_BINDINGS or ["#"]
            for rk in bindings:
                await _queue.bind(exchange, routing_key=rk)
                logger.info("Bound queue '%s' to '%s' with '%s'", _queue.name, settings.RABBITMQ_EXCHANGE, rk)

            logger.info("RabbitMQ connection ready")
            return
        except Exception as e:
            attempt += 1
            wait = min(30, 1 + attempt * 1.5) + random.uniform(0, 0.75)
            logger.exception("RabbitMQ connect failed (attempt %d): %s. Retrying in %.1fs ...", attempt, e, wait)
            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=wait)
            except asyncio.TimeoutError:
                continue


def _safe_json(body: bytes):
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return {"raw": body.decode("utf-8", errors="replace")}


async def _message_handler(message: AbstractIncomingMessage) -> None:
    """
    ACK and fan out to WebSocket clients with a small enrichment envelope.
    """
    async with message.process(ignore_processed=True):
        try:
            payload_obj = _safe_json(message.body)
            enriched = {
                "meta": {
                    "routing_key": message.routing_key,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "headers": dict(message.headers or {}),
                    "content_type": getattr(message, "content_type", "application/json"),
                },
                "data": payload_obj,
            }
            await websocket_manager.broadcast(enriched)
        except Exception as e:
            logger.exception("Failed to broadcast message to websockets: %s", e)


async def _consume() -> None:
    """
    Main consumer loop. Reconnects on failures.
    """
    while not _stop_event.is_set():
        await _ensure_connected()
        if _stop_event.is_set():
            break

        try:
            assert _queue is not None
            logger.info("Starting consumption on queue '%s'", _queue.name)
            await _queue.consume(_message_handler, no_ack=False)
            await _stop_event.wait()  # wait until shutdown requested
        except Exception as e:
            logger.exception("Consumer error, will attempt to reconnect: %s", e)
            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                continue

    logger.info("Stopped consumer main loop")


async def start_rabbit_consumer() -> None:
    _stop_event.clear()
    await _consume()


async def stop_rabbit_consumer() -> None:
    _stop_event.set()
    try:
        if _channel and not _channel.is_closed:
            await _channel.close()
    except Exception as e:
        logger.warning("Error closing channel: %s", e)

    try:
        if _connection and not _connection.is_closed:
            await _connection.close()
    except Exception as e:
        logger.warning("Error closing connection: %s", e)

    logger.info("Rabbit consumer stopped")
