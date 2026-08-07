# app/services/ingestion_service.py
"""Ingestion business logic: fetch details, record, resolve, dispatch, reconcile.

Flow for one ``trigger_raised`` event:
  1. Fetch the full envelope from the store; create a ``received`` record.
  2. Resolve the envelope against the process-registry:
       * match       → persist resolution, transition ``dispatched``, publish
                       ``trigger_dispatched`` for the agent-runtime.
       * no match    → transition ``no_process`` (terminal).
       * unreachable → stay ``received``; the retry sweep re-attempts later.
  3. The runtime's replies (``dispatch_accepted`` / ``dispatch_rejected``) drive
     ``dispatched → accepted``/``rejected`` (see ``handle_reply``).

The registry client + publisher are optional so the fetch-and-record core can be
exercised in isolation; when both are wired the full lifecycle runs.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from amendia_common.events import DISPATCH_ACCEPTED, DISPATCH_REJECTED
from amendia_contracts.dispatch import (
    DispatchResolution,
    Trace,
    TriggerDispatchedEvent,
)

from app.clients.registry_client import (
    RegistryClient,
    RegistryNoMatch,
    RegistryUnavailable,
)
from app.clients.stub_client import TriggerStoreClient
from app.dal.ingestion_repo import IngestionRepository
from app.events.publisher import RabbitPublisher
from app.logging_conf import trigger_id_ctx
from app.models.events import IncomingTriggerRaisedEvent
from app.models.ingestion import EventRef, IngestionRecord, IngestionStatus

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IngestionService:
    def __init__(
        self,
        repo: IngestionRepository,
        stub_client: TriggerStoreClient,
        registry_client: Optional[RegistryClient] = None,
        publisher: Optional[RabbitPublisher] = None,
    ) -> None:
        self._repo = repo
        self._stub = stub_client
        self._registry = registry_client
        self._publisher = publisher

    async def handle_event(self, event: IncomingTriggerRaisedEvent, routing_key: str) -> None:
        """Fetch details, create a received record, then resolve + dispatch."""
        token = trigger_id_ctx.set(event.trigger_id)
        try:
            detail = None
            fetch_error = None
            try:
                detail = await self._stub.fetch_trigger(event.trigger_id, event.fetch_url)
            except Exception as exc:  # noqa: BLE001 - record the failure, still log the event
                fetch_error = f"failed to fetch trigger details: {exc}"
                logger.error("Fetch failed for trigger_id=%s: %s", event.trigger_id, exc)

            record = await self._repo.create_received(
                trigger_id=event.trigger_id,
                trigger_type=event.trigger_type,
                event=EventRef(
                    event_id=event.event_id,
                    occurred_at=event.occurred_at,
                    schema_version=event.schema_version,
                    routing_key=routing_key,
                    fetch_url=event.fetch_url,
                ),
                detail=detail,
                fetch_error=fetch_error,
            )

            if record is None:
                logger.info("Duplicate trigger_id=%s already ingested; skipping", event.trigger_id)
                return

            logger.info(
                "Ingested trigger_id=%s status=received fetched=%s",
                event.trigger_id, detail is not None,
            )
            await self._resolve_and_dispatch(record)
        finally:
            trigger_id_ctx.reset(token)

    async def resolve_pending(self) -> int:
        """Retry-sweep: re-resolve records stuck in ``received`` (registry was down)."""
        if self._registry is None or self._publisher is None:
            return 0
        records = await self._repo.list_by_status(IngestionStatus.RECEIVED)
        dispatched = 0
        for rec in records:
            token = trigger_id_ctx.set(rec.trigger_id)
            try:
                if await self._resolve_and_dispatch(rec):
                    dispatched += 1
            finally:
                trigger_id_ctx.reset(token)
        if records:
            logger.info("Resolve sweep: %d received, %d newly dispatched", len(records), dispatched)
        return dispatched

    async def _resolve_and_dispatch(self, record: IngestionRecord) -> bool:
        """Resolve one received record; returns True if it was dispatched."""
        if self._registry is None or self._publisher is None:
            return False  # resolve/dispatch not wired (isolated core)

        envelope = record.trigger_detail
        if envelope is None:
            logger.warning(
                "trigger_id=%s has no fetched envelope; cannot resolve, leaving received",
                record.trigger_id,
            )
            return False

        try:
            resolved = await self._registry.resolve(envelope)
        except RegistryNoMatch as nm:
            await self._repo.mark_no_process(
                record.trigger_id, no_match=nm.body,
                detail=f"no active pack matched: {nm}",
            )
            logger.info("trigger_id=%s → no_process (%s)", record.trigger_id, nm)
            return False
        except RegistryUnavailable as exc:
            logger.warning(
                "registry unavailable for trigger_id=%s; leaving received for sweep: %s",
                record.trigger_id, exc,
            )
            return False

        resolution = {
            "pack_key": resolved["pack_key"],
            "pack_version": resolved["pack_version"],
            "rule_id": resolved["rule_id"],
            "resolved_at": resolved.get("resolved_at"),
        }
        updated = await self._repo.mark_dispatched(record.trigger_id, resolution=resolution)
        if updated is None:
            # Already dispatched (concurrent handler / sweep race) — nothing to do.
            return False

        dispatched_event = TriggerDispatchedEvent(
            event_id=uuid.uuid4().hex,
            occurred_at=_utcnow(),
            trigger_id=record.trigger_id,
            trigger_type=record.trigger_type,
            trigger_schema_version=record.event.schema_version,
            fetch_url=record.event.fetch_url,
            resolution=DispatchResolution(**resolution),
            trace=Trace(correlation_id=record.trigger_id, causation_id=record.event.event_id),
        )
        await self._publisher.publish(
            dispatched_event.to_doc(), dispatched_event.routing_key(), dispatched_event.event_id
        )
        logger.info(
            "trigger_id=%s → dispatched pack=%s@%s rule=%s",
            record.trigger_id, resolution["pack_key"], resolution["pack_version"],
            resolution["rule_id"],
        )
        return True

    async def handle_reply(self, payload: dict, routing_key: str) -> None:
        """Consume the runtime's dispatch replies (accepted/rejected). Idempotent."""
        trigger_id = payload.get("trigger_id")
        if not trigger_id:
            logger.error("Reply missing trigger_id (routing_key=%s)", routing_key)
            return
        token = trigger_id_ctx.set(trigger_id)
        try:
            if DISPATCH_ACCEPTED in routing_key:
                pid = payload.get("process_instance_id")
                updated = await self._repo.mark_accepted(
                    trigger_id, process_instance_id=pid,
                    detail=f"accepted by runtime; instance={pid}",
                )
                if updated is None:
                    logger.info("accepted reply for trigger_id=%s ignored (not dispatched)", trigger_id)
                else:
                    logger.info("trigger_id=%s → accepted instance=%s", trigger_id, pid)
            elif DISPATCH_REJECTED in routing_key:
                rejection = {"reason": payload.get("reason"), "detail": payload.get("detail")}
                updated = await self._repo.mark_rejected(
                    trigger_id, rejection=rejection,
                    detail=f"rejected by runtime: {rejection['reason']}",
                )
                if updated is None:
                    logger.info("rejected reply for trigger_id=%s ignored (not dispatched)", trigger_id)
                else:
                    logger.info("trigger_id=%s → rejected reason=%s", trigger_id, rejection["reason"])
            else:
                logger.warning("Unknown reply routing_key=%s", routing_key)
        finally:
            trigger_id_ctx.reset(token)
