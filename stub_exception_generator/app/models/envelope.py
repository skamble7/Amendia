# app/models/envelope.py
"""The normalized wire-transfer exception envelope and its stored wrapper.

The envelope model (``pin.payments.wire_exception``) now lives in
``amendia_contracts.wire_exception`` so both the stub (producer) and the
agent-runtime (consumer) validate against one shared model. This module
re-exports it for backward compatibility and keeps ``StoredException`` — the
store-managed persistence wrapper — local, since only the stub persists.
"""
from __future__ import annotations

from datetime import datetime

from amendia_contracts.wire_exception import (
    SCHEMA_VERSION,
    Account,
    Agent,
    Attachment,
    MonetaryAmount,
    Party,
    PaymentDetails,
    RelatedMessage,
    Source,
    WireExceptionEnvelope,
)

__all__ = [
    "SCHEMA_VERSION",
    "Account",
    "Agent",
    "Attachment",
    "MonetaryAmount",
    "Party",
    "PaymentDetails",
    "RelatedMessage",
    "Source",
    "WireExceptionEnvelope",
    "StoredException",
]


class StoredException(WireExceptionEnvelope):
    """Envelope wrapped with store-managed metadata (as persisted in Mongo)."""

    schema_version: str = SCHEMA_VERSION
    created_at: datetime
    updated_at: datetime
