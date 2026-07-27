# app/dining_generator.py
"""Synthetic dine-in order-ticket generator (pure, no I/O).

Mirrors :mod:`app.generator` (the wire path): given optional caller-pinned fields, produces a fully-formed
``OrderTicketEnvelope`` whose ``order_type`` is ALWAYS ``"dine_in"`` — the field the registry triage rule
matches to route the ticket to the ``restaurant-dinein`` pack. Anything unpinned is randomized within safe
sets. Three steerable flags drive the pack's three rework loops deterministically for demos.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import List, Optional

from amendia_contracts.order_ticket import OrderTicketEnvelope

from app.models.dining_api import GenerateTicketRequest

# House-menu items the restaurant-dinein MCP server knows (its handlers.get_menu). Producer-side domain data —
# exactly like the wire generator's reason codes — kept here, never in the platform image.
HAPPY_ITEMS = ["Margherita Pizza", "Grilled Salmon", "Sorbet"]  # available, no nuts → clean happy path
EIGHTY_SIXED_ITEM = "Lobster Thermidor (86)"  # available:false / name has "86" → validate_order → needs_info
ALLERGEN_ITEM = "Peanut Parfait"              # tags ["nuts"] → screen_allergens → conflict vs a nuts flag

_TABLES = ["T4", "T7", "T12", "T21", "B2", "P1"]
_CLEAN_TENDERS = ["card", "cash", "mobile"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_ticket_id(now: datetime) -> str:
    # TKT-<year>-<6-digit random>. Uniqueness is enforced by the DB index; the caller retries on collision.
    return f"TKT-{now.year}-{random.randint(0, 999_999):06d}"


def generate_ticket(req: GenerateTicketRequest, now: Optional[datetime] = None) -> OrderTicketEnvelope:
    """Produce one synthetic dine-in order ticket. ``order_type`` is invariant so triage always routes it."""
    now = now or _now()

    table = req.table or random.choice(_TABLES)
    party_size = req.party_size if req.party_size is not None else random.randint(1, 6)

    items: List[str] = list(HAPPY_ITEMS)
    dietary: List[str] = ["nuts"]  # party-level allergen flag (matches the sample); harmless on the happy path

    if req.include_86_item and EIGHTY_SIXED_ITEM not in items:
        items.append(EIGHTY_SIXED_ITEM)                     # → order-revise loop
    if req.allergen_conflict:
        if "nuts" not in dietary:
            dietary.append("nuts")
        if ALLERGEN_ITEM not in items:
            items.append(ALLERGEN_ITEM)                     # → allergen-revise loop

    # tender: the explicit flag wins (payment-resolve loop), else a pinned value, else a clean capture.
    if req.tender_declined:
        tender: Optional[str] = "declined"
    elif req.tender is not None:
        tender = req.tender
    else:
        tender = random.choice(_CLEAN_TENDERS)

    return OrderTicketEnvelope(
        ticket_id=_new_ticket_id(now),
        order_type="dine_in",
        table=table,
        party_size=party_size,
        dietary_flags=dietary,
        requested_items=items,
        tender=tender,
        seated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
