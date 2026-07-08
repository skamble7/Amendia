# app/models/ingestion.py
"""The ingestion-log record and its lifecycle.

Lifecycle:
  1. ``received``   — event consumed + details fetched + record created.
  2. ``dispatched`` — resolved to a pack and handed to the agent runtime.
  3. ``accepted`` / ``rejected`` — the runtime's dispatch reply.
  * ``no_process``  — the registry found no matching pack (terminal, off ``received``).

Illegal transitions are guarded in the repository so redelivered/replayed events
never corrupt state.
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
    NO_PROCESS = "no_process"  # registry found no matching pack (terminal)


class ResolutionRef(BaseModel):
    """The pinned pack the registry resolved this exception to."""

    pack_key: str
    pack_version: str
    rule_id: str
    resolved_at: Optional[str] = None


class RejectionRef(BaseModel):
    """The runtime's dispatch rejection detail."""

    reason: str
    detail: Optional[str] = None


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
    # Populated as the lifecycle advances (agent-runtime dispatch).
    resolution: Optional[ResolutionRef] = None
    process_instance_id: Optional[str] = None
    no_match: Optional[Dict[str, Any]] = None
    rejection: Optional[RejectionRef] = None
    created_at: datetime
    updated_at: datetime
