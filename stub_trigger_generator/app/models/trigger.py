# app/models/trigger.py
"""The single, domain-blind stored trigger message (ADR-059 D2).

One generic wrapper replaces the per-domain ``StoredException`` / ``StoredTicket``. The store never reads
a domain field: the whole domain envelope lives under ``payload``; ``trigger_id`` / ``trigger_type`` are
the platform key + discriminator (set by the router from each domain's own id/discriminator), and
``source`` is the producing generator id (``wire`` / ``dine_in``) — never a domain term.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel


class StoredTrigger(BaseModel):
    trigger_id: str
    trigger_type: str
    schema_version: str
    source: str
    payload: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
