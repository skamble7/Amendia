# amendia_contracts/order_ticket.py
"""Dine-in order-ticket trigger envelope (``pin.dining.order_ticket``).

Sibling of :mod:`app.contracts.wire_exception`: the shared, typed shape of the event that STARTS the
restaurant dine-in process — a seated party ready to order. The stub generator (producer) emits it, and the
process-registry triage rule matches it to the ``restaurant-dinein`` pack on ``order_type == "dine_in"``.

Like the wire envelope, this is a plain ``pydantic.BaseModel`` (a payload contract, not an event) — the pin is
a ``schema_version`` string, not an ``artifact_key``. The agent-runtime never imports it: the runtime validates
the fetched payload against the pack's DECLARED trigger JSON-Schema (ADR-047 D1, domain-neutral), so this
module is for the producer (stub) and any typed consumer.

Mirrors backend/docs/methodology/worked-examples/restaurant/schemas/art.dining.order_ticket.json@1.0.0.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# schema_version pin (mirrors wire_exception.SCHEMA_VERSION) — carried on the raised event, not an artifact_key.
SCHEMA_VERSION = "pin.dining.order_ticket/1.0"


class OrderTicketEnvelope(BaseModel):
    """``art.dining.order_ticket@1.0.0`` — the dine-in process trigger. Triage matches on ``order_type``."""

    ticket_id: str
    order_type: Literal["dine_in"] = "dine_in"
    table: Optional[str] = None
    party_size: Optional[int] = Field(default=None, ge=1)
    dietary_flags: List[str] = Field(default_factory=list)
    requested_items: List[str] = Field(default_factory=list)
    tender: Optional[str] = None
    seated_at: Optional[str] = None
