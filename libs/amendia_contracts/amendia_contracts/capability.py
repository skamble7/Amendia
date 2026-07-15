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
    # ADR-021 — a bounded agent loop (LangChain Deep Agents harness) inside one node.
    # Additive: existing descriptors/packs are unaffected. Runnable only in nemoclaw mode,
    # always behind a HITL gate, always memoized. The contract boundary is the guarantee.
    DEEP_AGENT = "deep_agent"


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
    """Self-descriptive MCP server binding (ADR-024). The connection details live directly on
    the capability descriptor — no config-forge/registry indirection."""

    kind: Literal["mcp"]
    endpoint: str                                    # MCP server URL (self-descriptive; was server_key)
    tools: List[str] = Field(..., min_length=1)
    transport: McpTransport = McpTransport.STREAMABLE_HTTP
    # Non-secret headers or secret-REFS only (env:/file:/vault:) — never a literal secret (ADR-016 trap 1).
    headers: Dict[str, str] = Field(default_factory=dict)


class LlmRuntime(ContractModel):
    kind: Literal["llm"]
    prompt_key: str
    model_config_key: Optional[str] = None
    structured_output: bool = True


class DeepAgentBudget(ContractModel):
    """Hard budget caging a deep_agent loop (ADR-021)."""

    max_steps: int = Field(default=12, ge=1, le=200)      # → LangGraph recursion_limit
    max_tokens: Optional[int] = Field(default=None, ge=1)


class DeepAgentRuntime(ContractModel):
    """A bounded Deep Agents Code loop. ``tools`` is the **whitelisted** toolset (MCP tool
    ids and/or named worker functions); the harness may use nothing else. ``model_config_key``
    should resolve to a managed/``nemoclaw`` ref. ``structured_output`` requires the harness
    to emit an object validating against the declared output artifact schema (host-validated).
    """

    kind: Literal["deep_agent"]
    prompt_key: str
    model_config_key: Optional[str] = None
    tools: List[str] = Field(..., min_length=1)
    structured_output: bool = True
    budget: DeepAgentBudget = Field(default_factory=DeepAgentBudget)


Runtime = Union[SkillRuntime, McpRuntime, LlmRuntime, DeepAgentRuntime]


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
