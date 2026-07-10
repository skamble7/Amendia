# app/services/ingestion_service.py
"""Ingestion business logic: fetch details, record, resolve, dispatch, reconcile.

Flow for one ``exception_raised`` event:
  1. Fetch the full envelope from the store; create a ``received`` record.
  2. Resolve the envelope against the process-registry:
       * match       → persist resolution, transition ``dispatched``, publish
                       ``exception_dispatched`` for the agent-runtime.
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
    ExceptionDispatchedEvent,
    Trace,
)

from app.clients.registry_client import (
    RegistryClient,
    RegistryNoMatch,
    RegistryUnavailable,
)
from app.clients.stub_client import StubClient
from app.dal.ingestion_repo import IngestionRepository
from app.events.publisher import RabbitPublisher
from app.logging_conf import exception_id_ctx
from app.models.events import IncomingExceptionRaisedEvent
from app.models.ingestion import EventRef, IngestionRecord, IngestionStatus

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IngestionService:
    def __init__(
        self,
        repo: IngestionRepository,
        stub_client: StubClient,
        registry_client: Optional[RegistryClient] = None,
        publisher: Optional[RabbitPublisher] = None,
    ) -> None:
        self._repo = repo
        self._stub = stub_client
        self._registry = registry_client
        self._publisher = publisher

    async def handle_event(self, event: IncomingExceptionRaisedEvent, routing_key: str) -> None:
        """Fetch details, create a received record, then resolve + dispatch."""
        token = exception_id_ctx.set(event.exception_id)
        try:
            detail = None
            fetch_error = None
            try:
                detail = await self._stub.fetch_exception(event.exception_id)
            except Exception as exc:  # noqa: BLE001 - record the failure, still log the event
                fetch_error = f"failed to fetch exception details: {exc}"
                logger.error("Fetch failed for exception_id=%s: %s", event.exception_id, exc)

            record = await self._repo.create_received(
                exception_id=event.exception_id,
                exception_type=event.exception_type,
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
                logger.info("Duplicate exception_id=%s already ingested; skipping", event.exception_id)
                return

            logger.info(
                "Ingested exception_id=%s status=received fetched=%s",
                event.exception_id, detail is not None,
            )
            await self._resolve_and_dispatch(record)
        finally:
            exception_id_ctx.reset(token)

    async def resolve_pending(self) -> int:
        """Retry-sweep: re-resolve records stuck in ``received`` (registry was down)."""
        if self._registry is None or self._publisher is None:
            return 0
        records = await self._repo.list_by_status(IngestionStatus.RECEIVED)
        dispatched = 0
        for rec in records:
            token = exception_id_ctx.set(rec.exception_id)
            try:
                if await self._resolve_and_dispatch(rec):
                    dispatched += 1
            finally:
                exception_id_ctx.reset(token)
        if records:
            logger.info("Resolve sweep: %d received, %d newly dispatched", len(records), dispatched)
        return dispatched

    async def _resolve_and_dispatch(self, record: IngestionRecord) -> bool:
        """Resolve one received record; returns True if it was dispatched."""
        if self._registry is None or self._publisher is None:
            return False  # resolve/dispatch not wired (isolated core)

        envelope = record.exception_detail
        if envelope is None:
            logger.warning(
                "exception_id=%s has no fetched envelope; cannot resolve, leaving received",
                record.exception_id,
            )
            return False

        try:
            resolved = await self._registry.resolve(envelope)
        except RegistryNoMatch as nm:
            await self._repo.mark_no_process(
                record.exception_id, no_match=nm.body,
                detail=f"no active pack matched: {nm}",
            )
            logger.info("exception_id=%s → no_process (%s)", record.exception_id, nm)
            return False
        except RegistryUnavailable as exc:
            logger.warning(
                "registry unavailable for exception_id=%s; leaving received for sweep: %s",
                record.exception_id, exc,
            )
            return False

        resolution = {
            "pack_key": resolved["pack_key"],
            "pack_version": resolved["pack_version"],
            "rule_id": resolved["rule_id"],
            "resolved_at": resolved.get("resolved_at"),
        }
        updated = await self._repo.mark_dispatched(record.exception_id, resolution=resolution)
        if updated is None:
            # Already dispatched (concurrent handler / sweep race) — nothing to do.
            return False

        dispatched_event = ExceptionDispatchedEvent(
            event_id=uuid.uuid4().hex,
            occurred_at=_utcnow(),
            exception_id=record.exception_id,
            exception_type=record.exception_type,
            exception_schema_version=record.event.schema_version,
            fetch_url=record.event.fetch_url,
            resolution=DispatchResolution(**resolution),
            trace=Trace(correlation_id=record.exception_id, causation_id=record.event.event_id),
        )
        await self._publisher.publish(
            dispatched_event.to_doc(), dispatched_event.routing_key(), dispatched_event.event_id
        )
        logger.info(
            "exception_id=%s → dispatched pack=%s@%s rule=%s",
            record.exception_id, resolution["pack_key"], resolution["pack_version"],
            resolution["rule_id"],
        )
        return True

    async def handle_reply(self, payload: dict, routing_key: str) -> None:
        """Consume the runtime's dispatch replies (accepted/rejected). Idempotent."""
        exception_id = payload.get("exception_id")
        if not exception_id:
            logger.error("Reply missing exception_id (routing_key=%s)", routing_key)
            return
        token = exception_id_ctx.set(exception_id)
        try:
            if DISPATCH_ACCEPTED in routing_key:
                pid = payload.get("process_instance_id")
                updated = await self._repo.mark_accepted(
                    exception_id, process_instance_id=pid,
                    detail=f"accepted by runtime; instance={pid}",
                )
                if updated is None:
                    logger.info("accepted reply for exception_id=%s ignored (not dispatched)", exception_id)
                else:
                    logger.info("exception_id=%s → accepted instance=%s", exception_id, pid)
            elif DISPATCH_REJECTED in routing_key:
                rejection = {"reason": payload.get("reason"), "detail": payload.get("detail")}
                updated = await self._repo.mark_rejected(
                    exception_id, rejection=rejection,
                    detail=f"rejected by runtime: {rejection['reason']}",
                )
                if updated is None:
                    logger.info("rejected reply for exception_id=%s ignored (not dispatched)", exception_id)
                else:
                    logger.info("exception_id=%s → rejected reason=%s", exception_id, rejection["reason"])
            else:
                logger.warning("Unknown reply routing_key=%s", routing_key)
        finally:
            exception_id_ctx.reset(token)
