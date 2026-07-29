# app/models/ticket.py
"""The dine-in party-seated envelope and its stored wrapper.

The envelope model (``pin.dining.party_seated``) lives in ``app.contracts.party_seated`` so the stub
(producer) and any typed consumer share one model — mirroring how ``app.models.envelope`` re-exports the wire
envelope. ``StoredTicket`` (the store-managed persistence wrapper) stays local, since only the stub persists.
"""
from __future__ import annotations

from datetime import datetime

from app.contracts.party_seated import SCHEMA_VERSION, PartySeatedEnvelope

__all__ = ["SCHEMA_VERSION", "PartySeatedEnvelope", "StoredTicket"]


class StoredTicket(PartySeatedEnvelope):
    """Party-seated trigger wrapped with store-managed metadata (as persisted in Mongo)."""

    schema_version: str = SCHEMA_VERSION
    created_at: datetime
    updated_at: datetime
