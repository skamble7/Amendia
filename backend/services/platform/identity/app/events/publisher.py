# app/events/publisher.py
"""Identity's outbound governed events (ADR-058 Phase B).

Identity had no event backbone before Phase B — role grant/revoke (and admin-protection refusals) are
governance-relevant, so they now publish a ``RoleChangedEvent`` on the canonical ``amendia.events``
topic exchange for glea-service to persist. Fail-soft everywhere: a broker hiccup never fails a role
change or blocks startup (identity works with the publisher absent/disconnected)."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message

from amendia_common.events import EXCHANGE
from amendia_contracts.governance_events import RoleChangedEvent, RoleChangeOp

logger = logging.getLogger(__name__)


class RabbitPublisher:
    def __init__(self, url: str) -> None:
        self._url = url
        self._connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractChannel] = None
        self._exchange: Optional[aio_pika.abc.AbstractExchange] = None

    async def connect(self) -> None:
        self._connection = await aio_pika.connect_robust(self._url, timeout=15)
        self._channel = await self._connection.channel(publisher_confirms=True)
        self._exchange = await self._channel.declare_exchange(EXCHANGE, ExchangeType.TOPIC, durable=True)
        logger.info("identity publisher connected, declared durable exchange '%s'", EXCHANGE)

    @property
    def is_ready(self) -> bool:
        return (self._connection is not None and not self._connection.is_closed
                and self._exchange is not None)

    async def publish(self, event: dict, routing_key: str, message_id: str) -> None:
        if self._exchange is None:
            raise RuntimeError("RabbitPublisher not connected")
        await self._exchange.publish(
            Message(body=json.dumps(event, default=str).encode("utf-8"),
                    content_type="application/json", delivery_mode=DeliveryMode.PERSISTENT,
                    message_id=message_id),
            routing_key=routing_key,
        )

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = self._channel = self._exchange = None


async def emit_role_changed(publisher: Optional[RabbitPublisher], *, subject_user: str, role: str,
                            op: str, actor: str, outcome: str) -> None:
    """Publish a RoleChangedEvent (grant/revoke, incl. a refused outcome). Fail-soft — never raises."""
    if publisher is None or not getattr(publisher, "is_ready", False):
        return
    try:
        ev = RoleChangedEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc),
            subject_user=subject_user, role=role, op=RoleChangeOp(op), actor=actor, outcome=outcome,
        )
        await publisher.publish(ev.to_doc(), ev.routing_key(), ev.event_id)
    except Exception as exc:  # noqa: BLE001 — governance audit must never break the role change
        logger.warning("failed to publish RoleChangedEvent (%s %s→%s): %s", op, actor, subject_user, exc)
