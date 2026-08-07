# app/models/events.py
"""The thin event published to RabbitMQ when a trigger is raised (ADR-059).

Deliberately NOT the full envelope — downstream services receive this and then call the stub's
fetch-back API (``fetch_url``) for the clean domain payload. Domain-neutral: ``trigger_type`` carries
the domain discriminator (wire ``exception_type`` / dine ``order_type``), set by the router.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TriggerRaisedEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = Field(default_factory=_utcnow)
    schema_version: str
    trigger_id: str
    trigger_type: str
    fetch_url: str
