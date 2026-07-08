# amendia_contracts/capability.py
"""Contract 2 — Capability descriptor.

Faithful implementation of the CapabilityDescriptor JSON Schema (contracts doc §2).
The only cross-field invariant that is self-contained in one document — runtime.kind
must equal the top-level kind — is enforced here. Registry-level checks (IO schema
compatibility with pack bindings, etc.) are # registry-validation and live elsewhere.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import Field, model_validator

from amendia_contracts.common import (
    ArtifactRef,
    CapabilityId,
    ContractModel,
    HitlMode,
    SemVerStr,
    TimestampsMixin,
)


class CapabilityKind(str, Enum):
    SKILL = "skill"
    MCP = "mcp"
    LLM = "llm"


class SideEffect(str, Enum):
    READ_ONLY = "read_only"
    SIDE_EFFECTFUL = "side_effectful"


class SchemaIO(ContractModel):
    """A named input/output bound to a versioned artifact schema."""

    name: str
    schema_: ArtifactRef = Field(..., alias="schema")
    required: bool = True


class McpTransport(str, Enum):
    STREAMABLE_HTTP = "streamable_http"
    STDIO = "stdio"
    SSE = "sse"


class SkillRuntime(ContractModel):
    kind: Literal["skill"]
    entrypoint: str


class McpRuntime(ContractModel):
    kind: Literal["mcp"]
    server_key: str
    tools: List[str] = Field(..., min_length=1)
    transport: McpTransport = McpTransport.STREAMABLE_HTTP


class LlmRuntime(ContractModel):
    kind: Literal["llm"]
    prompt_key: str
    model_config_key: Optional[str] = None
    structured_output: bool = True


Runtime = Union[SkillRuntime, McpRuntime, LlmRuntime]


class Constraints(ContractModel):
    timeout_seconds: int = 120
    max_retries: int = 2
    min_hitl_mode: Optional[HitlMode] = None


class CapabilityStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class CapabilityDescriptor(ContractModel, TimestampsMixin):
    descriptor_version: Literal["1.0"]
    capability_id: CapabilityId
    version: SemVerStr
    title: str
    description: Optional[str] = None
    kind: CapabilityKind
    side_effect: SideEffect
    idempotent: Optional[bool] = None
    inputs: List[SchemaIO]
    outputs: List[SchemaIO]
    config_schema: Optional[Dict[str, Any]] = None
    runtime: Runtime = Field(..., discriminator="kind")
    constraints: Optional[Constraints] = None
    owner: Optional[str] = None
    status: CapabilityStatus

    @model_validator(mode="after")
    def _runtime_kind_matches(self) -> "CapabilityDescriptor":
        if self.runtime.kind != self.kind.value:
            raise ValueError(
                f"runtime.kind '{self.runtime.kind}' must equal capability kind '{self.kind.value}'"
            )
        return self
