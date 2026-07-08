# app/models/registry.py
"""Registry-local models: resolve request/response and the activation resolution sub-doc."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from amendia_contracts.common import utcnow


# --------------------------------------------------------------------------- #
# Activation resolution (stored on the pack; lets the runtime load without re-resolving)
# --------------------------------------------------------------------------- #

class ResolvedIO(BaseModel):
    name: str
    schema_: str = Field(..., alias="schema")  # pinned art.*@x.y.z

    model_config = {"populate_by_name": True}


class ResolvedBinding(BaseModel):
    element_id: str
    executor_capability: Optional[str] = None  # pinned cap.*@x.y.z
    assist_capability: Optional[str] = None
    inputs: List[ResolvedIO] = Field(default_factory=list)
    outputs: List[ResolvedIO] = Field(default_factory=list)


class Resolution(BaseModel):
    resolved_at: datetime = Field(default_factory=utcnow)
    capabilities: Dict[str, str] = Field(default_factory=dict)   # capability_id -> pinned version
    artifacts: Dict[str, str] = Field(default_factory=dict)      # artifact_key  -> pinned version
    bindings: List[ResolvedBinding] = Field(default_factory=list)

    def to_doc(self) -> dict:
        return self.model_dump(mode="json", by_alias=True)


# --------------------------------------------------------------------------- #
# Resolve (triage lookup)
# --------------------------------------------------------------------------- #

class ResolveRequest(BaseModel):
    tenant: str
    envelope: Dict[str, Any]


class ResolveResponse(BaseModel):
    pack_key: str
    pack_version: str
    rule_id: str
    resolved_at: datetime = Field(default_factory=utcnow)


class NoMatchResponse(BaseModel):
    detail: str = "no active pack matched the exception"
    tenant: str
    considered_packs: int
