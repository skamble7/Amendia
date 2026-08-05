# app/events/publisher.py
"""config-forge's outbound governed events (ADR-058 fast-follow).

Config/credential-ref resolution is governance-relevant, so a resolve now publishes a
``ConfigRefResolvedEvent`` on the canonical ``amendia.events`` topic exchange for glea-service to
persist. config-forge had no broker plumbing before (it was the older standalone service). Fail-soft
everywhere: a broker hiccup never fails a resolution or blocks startup."""
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
from amendia_contracts.governance_events import ConfigRefResolvedEvent

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
        logger.info("config-forge publisher connected, declared durable exchange '%s'", EXCHANGE)

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


def _trace_id_from_current() -> Optional[str]:
    """The active span's trace id (32-hex) from the W3C traceparent, for the audit↔trace join. None
    when telemetry is off. Best-effort — never raises."""
    try:
        from amendia_telemetry import current_traceparent

        tp = current_traceparent()  # 00-<trace_id>-<span_id>-<flags>
        if tp:
            parts = tp.split("-")
            if len(parts) >= 2 and parts[1]:
                return parts[1]
    except Exception:  # noqa: BLE001
        pass
    return None


async def emit_config_ref_resolved(publisher: Optional[RabbitPublisher], *, ref: str, resolved: bool,
                                   actor: Optional[str] = None) -> None:
    """Publish a ConfigRefResolvedEvent (which ref, resolved-or-not — never the resolved VALUE).
    Fail-soft: a broker hiccup never breaks the resolution."""
    if publisher is None or not getattr(publisher, "is_ready", False):
        return
    try:
        ev = ConfigRefResolvedEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc),
            ref=ref, resolved=resolved, actor=actor,
            # No instance context here; key the audit row by the ref itself, stamp the request trace id.
            trace=Trace(correlation_id=ref, trace_id=_trace_id_from_current()),
        )
        await publisher.publish(ev.to_doc(), ev.routing_key(), ev.event_id)
    except Exception as exc:  # noqa: BLE001 — governance audit must never break resolution
        logger.warning("failed to publish ConfigRefResolvedEvent for %s: %s", ref, exc)
