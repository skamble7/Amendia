# amendia_contracts/wire_exception.py
"""The normalized wire-transfer exception envelope (``pin.payments.wire_exception``).

This is the business *payload* the stub generator emits and the agent-runtime
fetches + validates on dispatch — NOT a platform event, so it stays a plain
``BaseModel`` (no ContractModel envelope semantics). Structure mirrors
``backend/docs/wire-transfer-exception-reference.md`` §4 verbatim. The ``payment``
block is the wire-specific, pacs.008-shaped section, kept separate so other
exception types can swap it later.

Moved here from the stub in Step 3 so both the stub (producer) and the
agent-runtime (consumer) validate against one shared model. The stub keeps its
store-managed ``StoredException`` wrapper locally.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "pin.payments.wire_exception/1.0"


class Source(BaseModel):
    system: str
    channel: str


class MonetaryAmount(BaseModel):
    currency: str
    value: float


class Account(BaseModel):
    id: str
    scheme: str


class Party(BaseModel):
    name: str
    account: Optional[Account] = None


class Agent(BaseModel):
    bic: str


class PaymentDetails(BaseModel):
    """pacs.008-shaped payment block."""

    msg_type: str
    uetr: str
    instruction_id: str
    end_to_end_id: str
    settlement_amount: MonetaryAmount
    value_date: str
    debtor: Party
    debtor_agent: Agent
    creditor: Party
    creditor_agent: Agent
    charges: str


class RelatedMessage(BaseModel):
    type: str
    id: str
    assigner_bic: str


class Attachment(BaseModel):
    attachment_id: str
    name: str
    media_type: str
    sha256: str
    fetch_url: str


class WireExceptionEnvelope(BaseModel):
    """The business payload the generator emits."""

    exception_id: str
    source: Source
    received_at: str
    exception_type: str
    reason_codes: List[str]
    reason_narrative: str
    status: str
    payment: PaymentDetails
    related_messages: List[RelatedMessage] = Field(default_factory=list)
    attachments: List[Attachment] = Field(default_factory=list)
