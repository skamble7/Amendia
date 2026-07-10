# app/models/api.py
"""API request/response models for the exceptions router."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.envelope import StoredException

# The reason codes the triage rule matches (see reference doc §4).
ReasonCode = Literal["AC01", "AC04", "RC01", "BE04"]


class GenerateRequest(BaseModel):
    """Body for ``POST /exceptions/generate`` — every field is optional.

    Anything the caller pins is honored; the rest is randomized per exception.
    """

    reason_code: Optional[ReasonCode] = None
    amount: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = None
    include_attachments: Optional[bool] = None
    count: int = Field(default=1, ge=1, le=20)


class GeneratedItem(BaseModel):
    """One generated exception plus how it was published."""

    exception: StoredException
    routing_key: str
    published: bool
    warning: Optional[str] = None


class GenerateResponse(BaseModel):
    created: List[GeneratedItem]
