# app/models/envelope.py
"""The normalized wire-transfer exception envelope and its stored wrapper.

The envelope model (``pin.payments.wire_exception``) now lives in
``app.contracts.wire_exception`` so both the stub (producer) and the
agent-runtime (consumer) validate against one shared model. This module
re-exports it for backward compatibility re-exports it for shared use. Persistence now lives in the domain-blind StoredTrigger (models/trigger.py).
"""
from __future__ import annotations

from datetime import datetime

from app.contracts.wire_exception import (
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
]

