# app/models/envelope.py
"""The normalized wire-transfer exception envelope and its stored wrapper.

Structure mirrors ``backend/docs/wire-transfer-exception-reference.md`` §4
verbatim (``pin.payments.wire_exception``). The ``payment`` block is the
wire-specific, pacs.008-shaped section — kept clearly separated so other
exception types can swap it later. ``StoredException`` adds store-managed
metadata (schema_version + timestamps) that the service sets, not the caller.
"""
from __future__ import annotations

from datetime import datetime
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
    tenant: str
    source: Source
    received_at: str
    exception_type: str
    reason_codes: List[str]
    reason_narrative: str
    status: str
    payment: PaymentDetails
    related_messages: List[RelatedMessage] = Field(default_factory=list)
    attachments: List[Attachment] = Field(default_factory=list)


class StoredException(WireExceptionEnvelope):
    """Envelope wrapped with store-managed metadata (as persisted in Mongo)."""

    schema_version: str = SCHEMA_VERSION
    created_at: datetime
    updated_at: datetime
