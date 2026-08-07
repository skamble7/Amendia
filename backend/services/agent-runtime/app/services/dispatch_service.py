# app/services/dispatch_service.py
"""Handle ``trigger_dispatched``: idempotency, envelope fetch/validate, pack load,
instance creation, accept/reject reply, and kicking off execution.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from pydantic import ValidationError

from jsonschema import Draft202012Validator

from amendia_contracts.dispatch import (
    DispatchAcceptedEvent,
    DispatchRejectedEvent,
    DispatchRejectionReason,
    TriggerDispatchedEvent,
    Trace,
)

from app.clients.registry_client import TriggerStoreClient, RegistryError, RegistryNotFound
from app.dal.base import DuplicateError
from app.engine.engine import PackNotActive, PackRequiresProfile, ProcessEngine
from app.logging_conf import trigger_id_ctx
from app.models.process_instance import ProcessInstance, compute_idempotency_key

logger = logging.getLogger(__name__)


def _validate_trigger(envelope_doc: Any, trigger_schema: Optional[Dict[str, Any]]) -> Optional[str]:
    """ADR-047 D1 (domain-neutral): validate the fetched trigger payload against the pack's declared trigger
    schema. Returns a rejection reason string, or None when the envelope is acceptable. With no declared
    trigger schema the payload is opaque — only a non-object is rejected."""
    if trigger_schema:
        errors = sorted(Draft202012Validator(trigger_schema).iter_errors(envelope_doc),
                        key=lambda e: list(e.path))
        if errors:
            return f"envelope invalid: {[e.message for e in errors[:3]]}"
        return None
    if not isinstance(envelope_doc, dict):
        return f"envelope invalid: expected a JSON object, got {type(envelope_doc).__name__}"
    return None


class DispatchService:
    def __init__(
        self,
        *,
        engine: ProcessEngine,
        instance_repo,
        dispatch_repo,
        store_client: TriggerStoreClient,
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
            event = TriggerDispatchedEvent.model_validate(payload)
        except ValidationError as exc:
            logger.error("Dropping invalid trigger_dispatched: %s", exc)
            return

        token = trigger_id_ctx.set(event.trigger_id)
        try:
            await self._handle(event)
        finally:
            trigger_id_ctx.reset(token)

    async def _handle(self, event: TriggerDispatchedEvent) -> None:
        pack_key = event.resolution.pack_key
        pack_version = event.resolution.pack_version
        correlation_id = event.trace.correlation_id if event.trace else event.trigger_id

        # Record the inbound event (idempotent log; duplicates are fine).
        try:
            await self._dispatch_log.insert(event)
        except DuplicateError:
            logger.info("duplicate dispatch event_id=%s", event.event_id)

        # Idempotency: an existing instance → re-accept with the same instance id.
        idem = compute_idempotency_key(event.trigger_id, pack_key, pack_version)
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

        # Load the pack from the registry (validates unknown / not-active). Loaded FIRST so the envelope can
        # be validated against the pack's OWN declared trigger schema (ADR-047 D1) — the engine assumes no
        # concrete envelope type.
        try:
            bundle = await self._engine.load_bundle(pack_key, pack_version)
        except RegistryNotFound:
            await self._reject(event, DispatchRejectionReason.UNKNOWN_PACK,
                               f"pack {pack_key}@{pack_version} not found", correlation_id)
            return
        except PackNotActive as exc:
            await self._reject(event, DispatchRejectionReason.PACK_NOT_ACTIVE, str(exc), correlation_id)
            return
        except PackRequiresProfile as exc:
            await self._reject(event, DispatchRejectionReason.PACK_REQUIRES_PROFILE, str(exc), correlation_id)
            return
        except (RegistryError, ValueError) as exc:
            await self._reject(event, DispatchRejectionReason.UNKNOWN_PACK,
                               f"pack load failed: {exc}", correlation_id)
            return

        # ADR-047 D1: validate the envelope against the pack's DECLARED trigger artifact schema. When the pack
        # declares no trigger, the envelope is opaque — accept any JSON object, reject only a non-object.
        reason = _validate_trigger(envelope_doc, getattr(bundle, "trigger_schema", None))
        if reason is not None:
            await self._reject(event, DispatchRejectionReason.ENVELOPE_INVALID, reason, correlation_id)
            return

        # Create the instance (created), then accept + start execution.
        pid = f"pi-{uuid.uuid4().hex[:16]}"
        instance = ProcessInstance.new(
            process_instance_id=pid, trigger_id=event.trigger_id,
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

    async def _accept(self, event: TriggerDispatchedEvent, pid: str, correlation_id: str) -> None:
        await self._publish(DispatchAcceptedEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc),
            trigger_id=event.trigger_id, process_instance_id=pid,
            pack_key=event.resolution.pack_key, pack_version=event.resolution.pack_version,
            trace=Trace(correlation_id=correlation_id, causation_id=event.event_id),
        ))
        logger.info("dispatch accepted: trigger_id=%s instance=%s", event.trigger_id, pid)

    async def _reject(self, event: TriggerDispatchedEvent, reason: DispatchRejectionReason,
                      detail: str, correlation_id: str) -> None:
        await self._publish(DispatchRejectedEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc),
            trigger_id=event.trigger_id, reason=reason, detail=detail,
            trace=Trace(correlation_id=correlation_id, causation_id=event.event_id),
        ))
        logger.warning("dispatch rejected: trigger_id=%s reason=%s", event.trigger_id, reason.value)

    async def _publish(self, event) -> None:
        if self._publisher is None:
            return
        await self._publisher.publish(event.to_doc(), event.routing_key(), event.event_id)
