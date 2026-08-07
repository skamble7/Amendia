# app/models/dining_api.py
"""Request model for the dine-in generator (domain data). The generate response/wrapper models are
domain-neutral and live in ``routers/generators.py``."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class GenerateTicketRequest(BaseModel):
    """Body for ``POST /generators/dine_in/generate`` — every field optional.

    Anything the caller pins is honored; the rest is randomized within safe (triage-compatible) sets. The
    party-seated trigger is slim: the food order (86'd item, allergen item) comes from the diner's Select-items
    HITL task and the tender is captured later at the payment step, so those loop-drivers are no longer pinned
    here. ``with_nut_allergy`` flags a party-level allergy at seating, setting up the allergen screen.
    """

    table: Optional[str] = None
    party_size: Optional[int] = Field(default=None, ge=1)
    with_nut_allergy: bool = False  # party flags a nut allergy at seating → dietary_flags: ["nuts"]
    count: int = Field(default=1, ge=1, le=20)
