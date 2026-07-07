# app/models/ingestion.py
"""The ingestion-log record and its lifecycle.

Each ingested exception has a 3-stage lifecycle:
  1. ``received``   — event consumed + details fetched + record created (wired now).
  2. ``dispatched`` — handed to the agent runtime (future).
  3. ``accepted`` / ``rejected`` — the runtime's outcome (future).

Only ``received`` is set today; the later states + ``status_history`` exist so
the agent-runtime work slots in without a schema change.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class IngestionStatus(str, Enum):
    RECEIVED = "received"
    DISPATCHED = "dispatched"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class EventRef(BaseModel):
    """The thin event that triggered this ingestion (kept for audit)."""

    event_id: str
    occurred_at: datetime
    schema_version: str
    routing_key: str
    fetch_url: str


class StatusChange(BaseModel):
    status: IngestionStatus
    at: datetime
    detail: Optional[str] = None


class IngestionRecord(BaseModel):
    exception_id: str
    tenant: str
    exception_type: str
    event: EventRef
    # Full envelope fetched from the store; None if the fetch failed.
    exception_detail: Optional[Dict[str, Any]] = None
    fetch_error: Optional[str] = None
    status: IngestionStatus = IngestionStatus.RECEIVED
    status_history: List[StatusChange] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
