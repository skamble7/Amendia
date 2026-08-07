# app/models/api.py
"""Request model + reason-code set for the wire generator (domain data). The generate response/wrapper
models are domain-neutral and live in ``routers/generators.py`` (``GeneratedTrigger`` / ``GenerateResponse``)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# The reason codes the wire triage rule matches (see reference doc §4).
ReasonCode = Literal["AC01", "AC04", "RC01", "BE04"]


class GenerateRequest(BaseModel):
    """Body for ``POST /generators/wire/generate`` — every field is optional.

    Anything the caller pins is honored; the rest is randomized per trigger.
    """

    reason_code: Optional[ReasonCode] = None
    amount: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = None
    include_attachments: Optional[bool] = None
    count: int = Field(default=1, ge=1, le=20)
