# app/events/publisher.py
"""aio-pika publisher for the agent-runtime's outbound events.

Publishes dispatch replies (accepted/rejected), HITL thin events, and process
lifecycle events on the canonical ``amendia.events`` topic exchange. Mirrors the
stub/ingestor publishers.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message

from amendia_common.events import EXCHANGE
from amendia_contracts.dispatch import Trace
from amendia_contracts.governance_events import (
    CohortLifecycleEvent, CohortLifecycleOp, CohortSlaEvent, CohortSlaKind, CohortSlaState,
)

logger = logging.getLogger(__name__)


class RabbitPublisher:
    def __init__(self, url: str) -> None:
        self._url = url
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None

    async def connect(self) -> None:
        self._connection = await aio_pika.connect_robust(self._url, timeout=15)
        self._channel = await self._connection.channel(publisher_confirms=True)
        self._exchange = await self._channel.declare_exchange(
            EXCHANGE, ExchangeType.TOPIC, durable=True
        )
        logger.info("Publisher connected, declared durable topic exchange '%s'", EXCHANGE)

    async def publish(self, event: dict, routing_key: str, message_id: str) -> None:
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
        self._connection = None
        self._channel = None
        self._exchange = None


async def emit_cohort_lifecycle(
    publisher, *, op: str, cohort_def_id: str, cohort_instance_id: str, correlation_value: str,
    process_instance_id: Optional[str] = None, pack_key: Optional[str] = None,
    pack_version: Optional[str] = None, close_outcome: Optional[str] = None,
    detail: Optional[str] = None, trace: Optional[Trace] = None,
) -> None:
    """ADR-063 — publish a CohortLifecycleEvent (opened / member_joined / late_join / closing / closed).
    Fail-soft (mirrors process-registry's ``emit_pack_lifecycle``): a broker hiccup never breaks the segment's
    dispatch/execution — the cohort is observation, the segment is the product."""
    if publisher is None or not getattr(publisher, "is_ready", False):
        return
    try:
        ev = CohortLifecycleEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc),
            op=CohortLifecycleOp(op), cohort_def_id=cohort_def_id, cohort_instance_id=cohort_instance_id,
            correlation_value=correlation_value, process_instance_id=process_instance_id, pack_key=pack_key,
            pack_version=pack_version, close_outcome=close_outcome, detail=detail, trace=trace,
        )
        await publisher.publish(ev.to_doc(), ev.routing_key(), ev.event_id)
    except Exception as exc:  # noqa: BLE001 — cohort observation must never break execution
        logger.warning("failed to publish CohortLifecycleEvent (%s %s): %s", op, cohort_instance_id, exc)


async def emit_cohort_sla(
    publisher, *, state: str, cohort_def_id: str, cohort_instance_id: str, correlation_value: str,
    sla_id: str, kind: str, ref: str, owner: str, clock: str,
    due_at: Optional[str] = None, at_risk_at: Optional[str] = None, detected_at: Optional[str] = None,
    trace: Optional[Trace] = None,
) -> None:
    """ADR-064 P2 — publish a CohortSlaEvent (at_risk / breached / satisfied / voided). Fail-soft, exactly
    like ``emit_cohort_lifecycle``: a broker hiccup never breaks the segment or the cohort lifecycle — the SLA
    is observation. The agent-runtime SoR stays authoritative; GLEA (P3) consumes this off the bus."""
    if publisher is None or not getattr(publisher, "is_ready", False):
        return
    try:
        ev = CohortSlaEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc),
            state=CohortSlaState(state), cohort_def_id=cohort_def_id, cohort_instance_id=cohort_instance_id,
            correlation_value=correlation_value, sla_id=sla_id, kind=CohortSlaKind(kind), ref=ref,
            owner=owner, clock=clock, due_at=due_at, at_risk_at=at_risk_at, detected_at=detected_at,
            trace=trace,
        )
        await publisher.publish(ev.to_doc(), ev.routing_key(), ev.event_id)
    except Exception as exc:  # noqa: BLE001 — cohort observation must never break execution
        logger.warning("failed to publish CohortSlaEvent (%s %s %s): %s", state, cohort_instance_id, sla_id, exc)
