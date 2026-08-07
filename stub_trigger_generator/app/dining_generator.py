# app/dining_generator.py
"""Synthetic dine-in party-seated generator (pure, no I/O).

Mirrors :mod:`app.generator` (the wire path): given optional caller-pinned fields, produces a fully-formed
``PartySeatedEnvelope`` whose ``order_type`` is ALWAYS ``"dine_in"`` — the field the registry triage rule
matches to route the ticket to the ``restaurant-dinein`` pack. Anything unpinned is randomized within safe
sets. The trigger is slim (only what is known at seating): the food order comes from the diner's Select-items
HITL task and the tender is captured later at the payment step, so neither rides on the trigger.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import List, Optional

from app.contracts.party_seated import PartySeatedEnvelope

from app.models.dining_api import GenerateTicketRequest

_TABLES = ["T4", "T7", "T12", "T21", "B2", "P1"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_ticket_id(now: datetime) -> str:
    # TKT-<year>-<6-digit random>. Uniqueness is enforced by the DB index; the caller retries on collision.
    return f"TKT-{now.year}-{random.randint(0, 999_999):06d}"


def generate_ticket(req: GenerateTicketRequest, now: Optional[datetime] = None) -> PartySeatedEnvelope:
    """Produce one synthetic party-seated trigger. ``order_type`` is invariant so triage always routes it."""
    now = now or _now()

    table = req.table or random.choice(_TABLES)
    party_size = req.party_size if req.party_size is not None else random.randint(1, 6)
    dietary: List[str] = ["nuts"] if req.with_nut_allergy else []  # party-level allergen flagged at seating

    return PartySeatedEnvelope(
        ticket_id=_new_ticket_id(now),
        order_type="dine_in",
        table=table,
        party_size=party_size,
        dietary_flags=dietary,
        seated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
