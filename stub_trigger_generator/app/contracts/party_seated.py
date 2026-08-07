# amendia_contracts/party_seated.py
"""Dine-in party-seated trigger envelope (``pin.dining.party_seated``).

Sibling of :mod:`app.contracts.wire_exception`: the shared, typed shape of the event that STARTS the
restaurant dine-in process — a seated party, ready to order. The stub generator (producer) emits it, and the
process-registry triage rule matches it to the ``restaurant-dinein`` pack on ``order_type == "dine_in"``.

The envelope carries only what is known at seating: no food order (that comes from the diner's Select-items
HITL task) and no tender (captured later at the payment step). Renamed from ``order_ticket`` — a "ticket"
implies an order that does not exist yet at seating.

Like the wire envelope, this is a plain ``pydantic.BaseModel`` (a payload contract, not an event) — the pin is
a ``schema_version`` string, not an ``artifact_key``. The agent-runtime never imports it: the runtime validates
the fetched payload against the pack's DECLARED trigger JSON-Schema (ADR-047 D1, domain-neutral), so this
module is for the producer (stub) and any typed consumer.

Mirrors backend/docs/methodology/worked-examples/restaurant/schemas/art.dining.party_seated.json@1.0.0.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# schema_version pin (mirrors wire_exception.SCHEMA_VERSION) — carried on the raised event, not an artifact_key.
SCHEMA_VERSION = "pin.dining.party_seated/1.0"


class PartySeatedEnvelope(BaseModel):
    """``art.dining.party_seated@1.0.0`` — the dine-in process trigger. Triage matches on ``order_type``."""

    ticket_id: str
    order_type: Literal["dine_in"] = "dine_in"
    table: Optional[str] = None
    party_size: Optional[int] = Field(default=None, ge=1)
    dietary_flags: List[str] = Field(default_factory=list)
    seated_at: Optional[str] = None
