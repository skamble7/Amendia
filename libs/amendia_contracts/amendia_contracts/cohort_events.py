# amendia_contracts/cohort_events.py
"""ADR-063 Phase 2 — the cohort close-ingress event.

The external orchestrator emits a normal "process ended" message carrying the business key; the ingestor
recognises it (registry close-schema match) and publishes ``CohortCloseRequested`` for agent-runtime — the
owner of the cohort SoR — to drive ``open → closing → closed``. Structural / domain-neutral: ``correlation_value``
is the SOLE resolving handle (the external system never learns Amendia's ids); ``cohort_def_id`` is carried
for logging/validation only and is never required to resolve the cohort (the global-uniqueness invariant).
"""
from __future__ import annotations

from typing import ClassVar, Literal, Optional

from amendia_common.events import COHORT_CLOSE_REQUESTED, Service
from amendia_contracts.common import EventBase
from amendia_contracts.dispatch import Trace


class CohortCloseRequested(EventBase):
    _service: ClassVar[Service] = Service.INGESTOR
    _event_name: ClassVar[str] = COHORT_CLOSE_REQUESTED

    schema_version: Literal["pin.platform.cohort_close_requested/1.0"] = "pin.platform.cohort_close_requested/1.0"
    correlation_value: str                       # the sole handle — resolves the cohort instance on its own
    close_outcome: Optional[str] = None          # the orchestrator-reported overall outcome, if any
    cohort_def_id: Optional[str] = None          # informational (logging/validation) — never required to resolve
    trace: Trace
