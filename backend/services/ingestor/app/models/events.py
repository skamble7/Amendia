# app/models/events.py
"""The thin ``exception_raised`` event consumed off RabbitMQ.

Mirrors the shape published by the stub exception generator (ADR-007). The
ingestor validates the incoming JSON against this model, then fetches the full
document from the store.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IncomingExceptionRaisedEvent(BaseModel):
    event_id: str
    occurred_at: datetime
    schema_version: str
    exception_id: str
    tenant: str
    exception_type: str
    fetch_url: str
