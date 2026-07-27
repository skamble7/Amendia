# app/models/ticket.py
"""The dine-in order-ticket envelope and its stored wrapper.

The envelope model (``pin.dining.order_ticket``) lives in ``amendia_contracts.order_ticket`` so the stub
(producer) and any typed consumer share one model — mirroring how ``app.models.envelope`` re-exports the wire
envelope. ``StoredTicket`` (the store-managed persistence wrapper) stays local, since only the stub persists.
"""
from __future__ import annotations

from datetime import datetime

from amendia_contracts.order_ticket import SCHEMA_VERSION, OrderTicketEnvelope

__all__ = ["SCHEMA_VERSION", "OrderTicketEnvelope", "StoredTicket"]


class StoredTicket(OrderTicketEnvelope):
    """Order ticket wrapped with store-managed metadata (as persisted in Mongo)."""

    schema_version: str = SCHEMA_VERSION
    created_at: datetime
    updated_at: datetime
