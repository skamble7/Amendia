# app/services/ingestion_service.py
"""Ingestion business logic: fetch details for an event and log it.

Deliberately basic: it subscribes (via the consumer) to ``exception_raised``,
pulls the full document from the store, and records a ``received`` entry. Process
selection and agent-runtime dispatch are future scope.
"""
from __future__ import annotations

import logging

from app.clients.stub_client import StubClient
from app.dal.ingestion_repo import IngestionRepository
from app.logging_conf import exception_id_ctx
from app.models.events import IncomingExceptionRaisedEvent
from app.models.ingestion import EventRef

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, repo: IngestionRepository, stub_client: StubClient) -> None:
        self._repo = repo
        self._stub = stub_client

    async def handle_event(self, event: IncomingExceptionRaisedEvent, routing_key: str) -> None:
        """Handle one exception_raised event: fetch details + create a received record."""
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
                tenant=event.tenant,
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
            else:
                logger.info(
                    "Ingested exception_id=%s tenant=%s status=received fetched=%s",
                    event.exception_id,
                    event.tenant,
                    detail is not None,
                )
        finally:
            exception_id_ctx.reset(token)
