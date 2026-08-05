# app/events/consumer.py
"""The audit-event consumer (ADR-058 Phase B).

A **durable, named work-queue** bound to the audit-relevant routing keys on ``amendia.events`` —
deliberately NOT notification-service's exclusive/auto-delete broadcast queue: a named durable queue
lets events **accumulate while glea is down** and be consumed on restart, so nothing is lost. Ack
discipline is the crux:

  * parse/mapping failure (poison)  → ``reject(requeue=False)`` (drop; requeuing would loop forever),
  * ClickHouse unavailable          → ``nack(requeue=True)``   (KEEP the event — never ack-and-drop),
  * success                         → ``ack()``.

Idempotency is owned by the writer (ReplacingMergeTree by ``event_id``), so a requeue → redelivery never
double-counts.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, List, Optional

import aio_pika
import orjson
from aio_pika.abc import AbstractIncomingMessage

from amendia_common.events import (
    ARTIFACT_COMMITTED,
    CONFIG_REF_RESOLVED,
    DISPATCH_ACCEPTED,
    EGRESS_DECISION,
    EXCHANGE,
    HITL_TASK_CREATED,
    HITL_TASK_DECIDED,
    HITL_TASK_EXPIRED,
    MESSAGE_RECEIVED,
    PACK_LIFECYCLE,
    PROCESS_COMPLETED,
    PROCESS_FAILED,
    ROLE_CHANGED,
    Service,
    TIMER_FIRED,
    rk,
)

from app.clickhouse.client import StorageUnavailable
from app.config import settings
from app.events.mapper import UnmappableEvent

logger = logging.getLogger(__name__)

# Every governed/audit-relevant routing key glea persists. Additive: new governed events add a key here.
AUDIT_BINDING_KEYS: List[str] = [
    rk(Service.AGENT_RUNTIME, DISPATCH_ACCEPTED),     # instance created (lifecycle)
    rk(Service.AGENT_RUNTIME, PROCESS_COMPLETED),
    rk(Service.AGENT_RUNTIME, PROCESS_FAILED),
    rk(Service.AGENT_RUNTIME, HITL_TASK_CREATED),
    rk(Service.AGENT_RUNTIME, HITL_TASK_DECIDED),
    rk(Service.AGENT_RUNTIME, HITL_TASK_EXPIRED),
    rk(Service.AGENT_RUNTIME, TIMER_FIRED),
    rk(Service.AGENT_RUNTIME, MESSAGE_RECEIVED),
    rk(Service.AGENT_RUNTIME, EGRESS_DECISION),
    rk(Service.AGENT_RUNTIME, ARTIFACT_COMMITTED),
    rk(Service.IDENTITY, ROLE_CHANGED),
    rk(Service.PROCESS_REGISTRY, PACK_LIFECYCLE),
    rk(Service.CONFIG_FORGE, CONFIG_REF_RESOLVED),
]

# handler(routing_key, payload) — raises StorageUnavailable (→ requeue) or UnmappableEvent (→ drop).
Handler = Callable[[str, dict], Awaitable[None]]


class AuditConsumer:
    def __init__(self, url: str, handler: Handler, *,
                 queue_name: Optional[str] = None,
                 binding_keys: Optional[List[str]] = None) -> None:
        self._url = url
        self._handler = handler
        self._queue_name = queue_name or settings.AUDIT_QUEUE
        self._binding_keys = binding_keys or AUDIT_BINDING_KEYS
        self._stop = asyncio.Event()
        self._connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractChannel] = None
        self._queue: Optional[aio_pika.abc.AbstractQueue] = None

    @property
    def is_ready(self) -> bool:
        return self._connection is not None and not self._connection.is_closed

    async def _connect(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                self._connection = await aio_pika.connect_robust(self._url, timeout=15)
                self._channel = await self._connection.channel()
                await self._channel.set_qos(prefetch_count=settings.PREFETCH)
                exchange = await self._channel.declare_exchange(
                    EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
                )
                # Durable, named queue (competing consumers) — NOT exclusive/auto-delete.
                self._queue = await self._channel.declare_queue(self._queue_name, durable=True)
                for key in self._binding_keys:
                    await self._queue.bind(exchange, routing_key=key)
                logger.info("glea audit queue '%s' bound to %d keys on '%s'",
                            self._queue_name, len(self._binding_keys), EXCHANGE)
                return
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                wait = min(30, 1 + attempt * 1.5) + random.uniform(0, 0.75)
                logger.warning("glea connect failed (attempt %d): %s. Retry in %.1fs", attempt, exc, wait)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    continue

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        try:
            payload = orjson.loads(message.body)
        except Exception as exc:  # noqa: BLE001 — unparseable poison, never requeue
            logger.error("dropping unparseable message (rk=%s): %s", message.routing_key, exc)
            await message.reject(requeue=False)
            return
        try:
            await self._handler(message.routing_key or "", payload)
        except StorageUnavailable as exc:
            # The ONE case we keep the message: audit must lose nothing when ClickHouse is down. Pause
            # briefly first so a persistent outage throttles the requeue loop rather than hot-looping.
            logger.warning("ClickHouse unavailable — requeueing (rk=%s): %s", message.routing_key, exc)
            backoff = getattr(settings, "REQUEUE_BACKOFF_SECONDS", 0.0)
            if backoff > 0:
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:  # shutting down — let the redelivery happen on restart
                    pass
            await message.nack(requeue=True)
            return
        except UnmappableEvent as exc:
            logger.error("dropping unmappable message (rk=%s): %s", message.routing_key, exc)
            await message.reject(requeue=False)
            return
        except Exception as exc:  # noqa: BLE001 — logic/bad-row poison, never requeue
            logger.exception("dropping bad message (rk=%s): %s", message.routing_key, exc)
            await message.reject(requeue=False)
            return
        await message.ack()

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
                logger.exception("glea consumer error, will reconnect: %s", exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
        logger.info("glea audit consumer stopped")

    async def stop(self) -> None:
        self._stop.set()
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
