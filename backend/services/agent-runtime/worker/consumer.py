# worker/consumer.py
"""RabbitMQ consumer for capability-execution jobs (ADR-020).

Binds a durable queue to ``agent_runtime.capability_exec_request.v1`` (competing consumers —
scale by running more workers), runs each job through the shared core in a worker thread
(so blocking LLM/MCP calls don't stall the event loop), and publishes the correlated reply to
the requester's ``reply_to`` queue. Reconnect/ack discipline mirrors the dispatch consumer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Optional

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from amendia_common.events import CAPABILITY_EXEC_REQUEST, EXCHANGE, Service, rk

from app.engine.executor.worker_runner import run_job

logger = logging.getLogger(__name__)

REQUEST_RK = rk(Service.AGENT_RUNTIME, CAPABILITY_EXEC_REQUEST)


class CapabilityWorkerConsumer:
    def __init__(self, url: str, queue_name: str) -> None:
        self._url = url
        self._queue_name = queue_name
        self._stop = asyncio.Event()
        self._connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractChannel] = None
        self._queue: Optional[aio_pika.abc.AbstractQueue] = None
        self._default_exchange: Optional[aio_pika.abc.AbstractExchange] = None

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
                self._default_exchange = self._channel.default_exchange
                self._queue = await self._channel.declare_queue(self._queue_name, durable=True)
                await self._queue.bind(exchange, routing_key=REQUEST_RK)
                logger.info("capability-worker queue '%s' bound to '%s'", self._queue_name, REQUEST_RK)
                return
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                wait = min(30, 1 + attempt * 1.5) + random.uniform(0, 0.75)
                logger.warning("worker connect failed (attempt %d): %s. Retry in %.1fs", attempt, exc, wait)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    continue

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        async with message.process(ignore_processed=True):
            try:
                job = json.loads(message.body.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.error("dropping unparseable job: %s", exc)
                return
            # Run the (blocking) core off the event loop; run_job never raises.
            reply = await asyncio.to_thread(run_job, job)
            if message.reply_to and self._default_exchange is not None:
                await self._default_exchange.publish(
                    aio_pika.Message(
                        body=json.dumps(reply, default=str).encode("utf-8"),
                        content_type="application/json",
                        correlation_id=message.correlation_id,
                    ),
                    routing_key=message.reply_to,
                )

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
                logger.exception("worker consumer error, will reconnect: %s", exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
        logger.info("capability-worker consumer stopped")

    async def stop(self) -> None:
        self._stop.set()
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
