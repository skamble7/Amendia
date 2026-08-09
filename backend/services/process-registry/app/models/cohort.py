# app/models/cohort.py
"""ADR-063 Phase 2 — cohort DEFINITION (design-time), registered/queried in the process-registry.

A definition declares the correlation contract and the external end-of-process (close) message schema. A pack's
``cohort_membership`` points at one by ``cohort_def_id``. The registry owns close-schema knowledge, so it — not
the ingestor — classifies inbound close messages (folded into ``/resolve``). The cohort INSTANCE SoR lives in
agent-runtime (Phase 1); this is only the definition.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from amendia_contracts.common import utcnow


class CohortDefinitionBase(BaseModel):
    cohort_def_id: str = Field(..., description="Stable design-time id, e.g. 'wire_transfer_cohort'")
    display_name: Optional[str] = None
    description: Optional[str] = None
    # JSON Schema of the external end-of-process (close) message. Validated well-formed at register time; used to
    # RECOGNISE a close message at /resolve (never a leaked Amendia id — the external system stays cohort-unaware).
    close_schema: Dict[str, Any]
    # Dotpath into a matching close message → the correlation_value (the sole handle that resolves the instance).
    close_correlation_path: str
    # Optional dotpath → an overall outcome the orchestrator reports on close.
    close_outcome_path: Optional[str] = None


class CohortDefinitionCreate(CohortDefinitionBase):
    """Register-request body (no store timestamps)."""


class CohortDefinitionUpdate(BaseModel):
    """Inline-edit request body — the MUTABLE fields only. ``cohort_def_id`` is immutable (instances + pack
    ``cohort_membership`` key on it), so it is never in the body; the path parameter identifies the target."""
    display_name: Optional[str] = None
    description: Optional[str] = None
    close_schema: Dict[str, Any]
    close_correlation_path: str
    close_outcome_path: Optional[str] = None


class CohortDefinition(CohortDefinitionBase):
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def to_doc(self) -> dict:
        return self.model_dump(mode="json")


class SetCohortMembershipRequest(BaseModel):
    """Assign a pack version to a cohort (ADR-063). ``correlation_key`` is a dotpath into THIS pack's trigger."""
    cohort_def_id: str
    correlation_key: str
