# app/models/dining_api.py
"""API request/response models for the tickets router (mirrors app.models.api)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.ticket import StoredTicket


class GenerateTicketRequest(BaseModel):
    """Body for ``POST /tickets/generate`` — every field optional.

    Anything the caller pins is honored; the rest is randomized within safe (triage-compatible) sets. The three
    boolean flags each drive one of the restaurant-dinein pack's rework loops for a deterministic demo.
    """

    table: Optional[str] = None
    party_size: Optional[int] = Field(default=None, ge=1)
    tender: Optional[str] = None
    include_86_item: bool = False    # add an 86'd item  → order-revise loop
    allergen_conflict: bool = False  # nuts item vs flag → allergen-revise loop
    tender_declined: bool = False    # tender="declined" → payment-resolve loop
    count: int = Field(default=1, ge=1, le=20)


class GeneratedTicket(BaseModel):
    """One generated ticket plus how it was published."""

    ticket: StoredTicket
    routing_key: str
    published: bool
    warning: Optional[str] = None


class GenerateTicketResponse(BaseModel):
    created: List[GeneratedTicket]
