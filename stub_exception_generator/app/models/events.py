# app/models/events.py
"""The thin event published to RabbitMQ when an exception is raised.

Deliberately NOT the full envelope — downstream services receive this and then
call the stub's fetch-back API (``fetch_url``) for the full document.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.models.envelope import SCHEMA_VERSION, WireExceptionEnvelope


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExceptionRaisedEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = Field(default_factory=_utcnow)
    schema_version: str = SCHEMA_VERSION
    exception_id: str
    exception_type: str
    fetch_url: str

    @classmethod
    def from_envelope(cls, env: WireExceptionEnvelope, base_url: str) -> "ExceptionRaisedEvent":
        return cls(
            exception_id=env.exception_id,
            exception_type=env.exception_type,
            fetch_url=f"{base_url.rstrip('/')}/exceptions/{env.exception_id}",
        )
