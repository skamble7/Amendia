# app/models/message.py
"""Message subscription + pending-message models (ADR-031 Phase 2.4).

A ``MessageSubscription`` is the message-substrate sibling of a ``Timer``: one durable row per
element a parked instance is waiting on. Correlation is by **business anchor** (exception_id /
correlation_id) + ``message_name`` — no internal-instance-id leakage, no per-pack expressions.
A ``PendingMessage`` buffers an inbound message that arrived before its subscription registered
(the ordering race), delivered on registration.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import Field

from app.models.common import ContractModel, utcnow


class SubscriptionKind(str, Enum):
    CATCH = "catch"                 # messageIntermediateCatchEvent
    RECEIVE = "receive"             # receiveTask
    EVENT_GATEWAY = "event_gateway"  # a message arm of an eventBasedGateway


class SubscriptionStatus(str, Enum):
    PENDING = "pending"
    CONSUMED = "consumed"
    CANCELLED = "cancelled"


class MessageSubscription(ContractModel):
    subscription_id: str
    process_instance_id: str
    element_id: str                 # the catch/receive element (or event-gateway arm) id
    message_name: str
    exception_id: str
    correlation_id: str
    kind: SubscriptionKind
    status: SubscriptionStatus = SubscriptionStatus.PENDING
    # The LangGraph interrupt id to resume when a correlated message arrives. For an event-gateway
    # arm this is the GATEWAY's interrupt (all arms share it — first-wins resumes the gateway).
    interrupt_id: Optional[str] = None
    gateway_id: Optional[str] = None  # set for event_gateway arms (the owning gateway element)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PendingMessage(ContractModel):
    pending_id: str
    message_name: str
    exception_id: Optional[str] = None
    correlation_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=utcnow)
