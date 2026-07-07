# app/models/config_entry.py
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConfigKind(str, Enum):
    llm = "llm"
    # future: storage = "storage", messaging = "messaging"


def build_ref(
    env: str,
    kind: str,
    provider: Optional[str],
    platform: Optional[str],
    name: str,
) -> str:
    """
    Build the canonical config reference string.

    Format: {env}.{kind}[.{provider}][.{platform}].{name}

    Examples:
        prod.llm.openai.default
        prod.llm.anthropic.raina.primary
        dev.llm.openai.orko.agents
    """
    segments = [env, kind]
    if provider:
        segments.append(provider)
    if platform:
        segments.append(platform)
    segments.append(name)
    return ".".join(segments)


class ConfigEntryCreate(BaseModel):
    env: str = Field(..., description="Deployment environment: prod, dev, staging, global")
    kind: ConfigKind
    provider: Optional[str] = Field(default=None, description="Vendor/service: openai, anthropic, s3, ...")
    platform: Optional[str] = Field(default=None, description="Registering platform: raina, zeta, orko")
    name: str = Field(..., min_length=1, max_length=100, description="Short disambiguator: default, primary, fast")
    description: Optional[str] = None
    data: Dict[str, Any] = Field(..., description="Full config payload (ModelProfile fields for llm kind)")
    created_by: Optional[str] = None

    @field_validator("env", "provider", "platform", "name", mode="before")
    @classmethod
    def _lowercase(cls, v: Optional[str]) -> Optional[str]:
        return v.lower().strip() if isinstance(v, str) else v


class ConfigEntryUpdate(BaseModel):
    description: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class ConfigEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., alias="_id")
    ref: str = Field(..., description="Canonical reference: env.kind[.provider][.platform].name")
    env: str
    kind: ConfigKind
    provider: Optional[str] = None
    platform: Optional[str] = None
    name: str
    description: Optional[str] = None
    data: Dict[str, Any]
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
