# app/models/dining_api.py
"""API request/response models for the tickets router (mirrors app.models.api)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.ticket import StoredTicket


class GenerateTicketRequest(BaseModel):
    """Body for ``POST /tickets/generate`` — every field optional.

    Anything the caller pins is honored; the rest is randomized within safe (triage-compatible) sets. The
    party-seated trigger is slim: the food order (86'd item, allergen item) comes from the diner's Select-items
    HITL task and the tender is captured later at the payment step, so those loop-drivers are no longer pinned
    here. ``with_nut_allergy`` flags a party-level allergy at seating, setting up the allergen screen.
    """

    table: Optional[str] = None
    party_size: Optional[int] = Field(default=None, ge=1)
    with_nut_allergy: bool = False  # party flags a nut allergy at seating → dietary_flags: ["nuts"]
    count: int = Field(default=1, ge=1, le=20)


class GeneratedTicket(BaseModel):
    """One generated ticket plus how it was published."""

    ticket: StoredTicket
    routing_key: str
    published: bool
    warning: Optional[str] = None


class GenerateTicketResponse(BaseModel):
    created: List[GeneratedTicket]
