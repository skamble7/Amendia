# app/services/dispatch_service.py
"""Handle ``exception_dispatched``: idempotency, envelope fetch/validate, pack load,
instance creation, accept/reject reply, and kicking off execution.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from pydantic import ValidationError

from amendia_contracts.dispatch import (
    DispatchAcceptedEvent,
    DispatchRejectedEvent,
    DispatchRejectionReason,
    ExceptionDispatchedEvent,
    Trace,
)
from amendia_contracts.wire_exception import WireExceptionEnvelope

from app.clients.registry_client import ExceptionStoreClient, RegistryError, RegistryNotFound
from app.dal.base import DuplicateError
from app.engine.engine import PackNotActive, ProcessEngine
from app.logging_conf import exception_id_ctx
from app.models.process_instance import ProcessInstance, compute_idempotency_key

logger = logging.getLogger(__name__)


class DispatchService:
    def __init__(
        self,
        *,
        engine: ProcessEngine,
        instance_repo,
        dispatch_repo,
        store_client: ExceptionStoreClient,
        publisher,
    ) -> None:
        self._engine = engine
        self._instances = instance_repo
        self._dispatch_log = dispatch_repo
        self._store = store_client
        self._publisher = publisher
        self._tasks: Set[asyncio.Task] = set()

    async def handle(self, payload: Dict[str, Any], routing_key: str = "") -> None:
        try:
            event = ExceptionDispatchedEvent.model_validate(payload)
        except ValidationError as exc:
            logger.error("Dropping invalid exception_dispatched: %s", exc)
            return

        token = exception_id_ctx.set(event.exception_id)
        try:
            await self._handle(event)
        finally:
            exception_id_ctx.reset(token)

    async def _handle(self, event: ExceptionDispatchedEvent) -> None:
        pack_key = event.resolution.pack_key
        pack_version = event.resolution.pack_version
        correlation_id = event.trace.correlation_id if event.trace else event.exception_id

        # Record the inbound event (idempotent log; duplicates are fine).
        try:
            await self._dispatch_log.insert(event)
        except DuplicateError:
            logger.info("duplicate dispatch event_id=%s", event.event_id)

        # Idempotency: an existing instance → re-accept with the same instance id.
        idem = compute_idempotency_key(event.tenant, event.exception_id, pack_key, pack_version)
        existing = await self._instances.get_by_idempotency_key(idem)
        if existing is not None:
            logger.info("dispatch idempotent: instance %s already exists", existing.process_instance_id)
            await self._accept(event, existing.process_instance_id, correlation_id)
            return

        # Fetch the envelope from the store's fetch-back URL.
        try:
            envelope_doc = await self._store.fetch(event.fetch_url)
        except Exception as exc:  # noqa: BLE001
            await self._reject(event, DispatchRejectionReason.FETCH_FAILED,
                               f"envelope fetch failed: {exc}", correlation_id)
            return

        # Validate the envelope against the wire-exception model.
        try:
            WireExceptionEnvelope.model_validate(envelope_doc)
        except ValidationError as exc:
            await self._reject(event, DispatchRejectionReason.ENVELOPE_INVALID,
                               f"envelope invalid: {exc.errors()[:3]}", correlation_id)
            return

        # Load the pack from the registry (validates unknown / not-active).
        try:
            await self._engine.load_bundle(pack_key, pack_version)
        except RegistryNotFound:
            await self._reject(event, DispatchRejectionReason.UNKNOWN_PACK,
                               f"pack {pack_key}@{pack_version} not found", correlation_id)
            return
        except PackNotActive as exc:
            await self._reject(event, DispatchRejectionReason.PACK_NOT_ACTIVE, str(exc), correlation_id)
            return
        except (RegistryError, ValueError) as exc:
            await self._reject(event, DispatchRejectionReason.UNKNOWN_PACK,
                               f"pack load failed: {exc}", correlation_id)
            return

        # Create the instance (created), then accept + start execution.
        pid = f"pi-{uuid.uuid4().hex[:16]}"
        instance = ProcessInstance.new(
            process_instance_id=pid, tenant=event.tenant, exception_id=event.exception_id,
            pack_key=pack_key, pack_version=pack_version, correlation_id=correlation_id,
        )
        try:
            await self._instances.insert(instance)
        except DuplicateError:
            # Concurrent create → fall back to the existing instance.
            existing = await self._instances.get_by_idempotency_key(idem)
            if existing:
                await self._accept(event, existing.process_instance_id, correlation_id)
            return

        await self._accept(event, pid, correlation_id)
        self._spawn(self._engine.start(instance, envelope_doc))

    # ------------------------------------------------------------------ #
    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _accept(self, event: ExceptionDispatchedEvent, pid: str, correlation_id: str) -> None:
        await self._publish(DispatchAcceptedEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc), tenant=event.tenant,
            exception_id=event.exception_id, process_instance_id=pid,
            pack_key=event.resolution.pack_key, pack_version=event.resolution.pack_version,
            trace=Trace(correlation_id=correlation_id, causation_id=event.event_id),
        ))
        logger.info("dispatch accepted: exception_id=%s instance=%s", event.exception_id, pid)

    async def _reject(self, event: ExceptionDispatchedEvent, reason: DispatchRejectionReason,
                      detail: str, correlation_id: str) -> None:
        await self._publish(DispatchRejectedEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc), tenant=event.tenant,
            exception_id=event.exception_id, reason=reason, detail=detail,
            trace=Trace(correlation_id=correlation_id, causation_id=event.event_id),
        ))
        logger.warning("dispatch rejected: exception_id=%s reason=%s", event.exception_id, reason.value)

    async def _publish(self, event) -> None:
        if self._publisher is None:
            return
        await self._publisher.publish(event.to_doc(), event.routing_key(), event.event_id)
