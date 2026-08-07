# app/models/events.py
"""The thin ``trigger_raised`` event consumed off RabbitMQ.

Mirrors the shape published by the trigger source (the stub, ADR-007/059). The
ingestor validates the incoming JSON against this model, then fetches the full
document from the store.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IncomingTriggerRaisedEvent(BaseModel):
    event_id: str
    occurred_at: datetime
    schema_version: str
    trigger_id: str
    trigger_type: str
    fetch_url: str
