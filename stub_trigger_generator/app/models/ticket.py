# app/models/ticket.py
"""The dine-in party-seated envelope (domain trigger).

The envelope model (``pin.dining.party_seated``) lives in ``app.contracts.party_seated`` so the stub
(producer) and any typed consumer share one model — mirroring how ``app.models.envelope`` re-exports the
wire envelope. Persistence is now the domain-blind ``StoredTrigger`` (``models/trigger.py``).
"""
from __future__ import annotations

from app.contracts.party_seated import SCHEMA_VERSION, PartySeatedEnvelope

__all__ = ["SCHEMA_VERSION", "PartySeatedEnvelope"]
