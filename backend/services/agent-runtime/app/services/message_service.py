# app/services/message_service.py
"""MessageSubscriptionService (ADR-031 Phase 2.4) — the message-substrate sibling of TimerService.

Wraps the subscription repo + the pending-message ordering buffer. No wall-clock / network here;
delivery is driven by the engine (via the HTTP intake) so tests inject it directly.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from app.dal.message_repo import MessageSubscriptionRepository, PendingMessageRepository
from app.models.message import (
    MessageSubscription,
    PendingMessage,
    SubscriptionKind,
    SubscriptionStatus,
)


class MessageSubscriptionService:
    def __init__(self, subs: MessageSubscriptionRepository, pending: PendingMessageRepository) -> None:
        self._subs = subs
        self._pending = pending

    async def register(
        self, *, process_instance_id: str, element_id: str, message_name: str,
        exception_id: str, correlation_id: str, kind: SubscriptionKind,
        interrupt_id: Optional[str] = None, gateway_id: Optional[str] = None,
    ) -> MessageSubscription:
        sub = MessageSubscription(
            subscription_id=f"sub-{uuid.uuid4().hex[:12]}",
            process_instance_id=process_instance_id, element_id=element_id, message_name=message_name,
            exception_id=exception_id, correlation_id=correlation_id, kind=kind,
            interrupt_id=interrupt_id, gateway_id=gateway_id,
        )
        return await self._subs.register(sub)

    async def find_match(self, message_name: str, *, exception_id: Optional[str] = None,
                         correlation_id: Optional[str] = None,
                         status: SubscriptionStatus = SubscriptionStatus.PENDING) -> Optional[MessageSubscription]:
        return await self._subs.find_match(
            message_name, exception_id=exception_id, correlation_id=correlation_id, status=status)

    async def mark_consumed(self, subscription_id: str) -> Optional[MessageSubscription]:
        return await self._subs.mark(subscription_id, SubscriptionStatus.CONSUMED)

    async def cancel_others_for_instance(self, process_instance_id: str, *, keep_element_id: str) -> int:
        return await self._subs.cancel_others_for_instance(process_instance_id, keep_element_id=keep_element_id)

    async def cancel_for_instance(self, process_instance_id: str) -> int:
        return await self._subs.cancel_for_instance(process_instance_id)

    async def list_for_instance(self, process_instance_id: str) -> List[MessageSubscription]:
        return await self._subs.list_for_instance(process_instance_id)

    # ---- ordering buffer ----
    async def buffer_message(self, *, message_name: str, exception_id: Optional[str],
                             correlation_id: Optional[str], payload: Optional[dict]) -> None:
        await self._pending.buffer(PendingMessage(
            pending_id=f"pmsg-{uuid.uuid4().hex[:12]}", message_name=message_name,
            exception_id=exception_id, correlation_id=correlation_id, payload=payload))

    async def pop_buffered(self, message_name: str, *, exception_id: Optional[str] = None,
                           correlation_id: Optional[str] = None) -> Optional[PendingMessage]:
        return await self._pending.pop_match(
            message_name, exception_id=exception_id, correlation_id=correlation_id)
