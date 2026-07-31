# app/services/copilot/proposal.py
"""The copilot's structured LLM output (ADR-052 Phase 2a).

`CopilotProposal` is what the single semantic LLM call returns — a *proposal only*. Reconciliation
(`reconcile.py`) is authoritative: it overlays the proposal onto the onboarding session and enforces the
deterministic invariants (bijection, side-effect/HITL floors, ADR-051 gateway alignment, ADR-050/E1
human-authored artifacts), correcting the LLM where it violates a floor. So this model is deliberately
PERMISSIVE — a slightly-off proposal parses, then deterministic code disposes.

Domain-neutral: every field is generic (element ids, tool names, artifact/field names) — no business nouns.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExecutorProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str                                    # capability | human | message | call
    capability_tool: Optional[str] = None        # the introspected MCP tool name (capability)
    role: Optional[str] = None                   # role.<domain>.<lane> (human)
    message_name: Optional[str] = None           # message executor
    call: Optional[str] = None                   # callee pack (call executor)


class HitlProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mode: str = "none"                           # none | review_after | approve_result | approve_actions | manual
    role: Optional[str] = None


class InputMapProposal(BaseModel):
    """One tool/human input FIELD sourced from upstream. ``from_`` is 'artifact' or 'trigger'."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    field: str                                   # the input field the source fills
    from_: str = Field(default="trigger", alias="from")
    name: Optional[str] = None                   # upstream output name (from='artifact')
    path: Optional[str] = None                   # dotpath within the source (scalar/composite)
    # ADR-048/052: absent-tolerant when the source artifact isn't guaranteed to exist yet (loop-back / branch
    # producer). reconcile.py is AUTHORITATIVE for from='artifact' fields (it overrides this from the flow graph);
    # the LLM's value is only a hint, and it round-trips a chat-set flag on the (graph-less) chat path.
    optional: Optional[bool] = None


class ReadOnlyInputProposal(BaseModel):
    """An upstream artifact wired as READ-ONLY on-form context for a human task (ADR-048 for human tasks)."""
    model_config = ConfigDict(extra="ignore")
    name: str                                    # the binding input name for the read-only context artifact
    source_output: str                           # the upstream output name to read as context


class OutputProposal(BaseModel):
    """A binding output. For a human task, ``human_authored`` marks an artifact the human writes; its schema is
    DERIVED deterministically from the consuming tools' input shape (never invented)."""
    model_config = ConfigDict(extra="ignore")
    name: str                                    # the addressable output name (ADR-051)
    human_authored: bool = False


class ElementProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    element_id: str
    executor: ExecutorProposal
    hitl: HitlProposal = Field(default_factory=HitlProposal)
    output_name: Optional[str] = None            # capability output rename (ADR-051)
    outputs: List[OutputProposal] = Field(default_factory=list)         # human-authored outputs
    input_map: List[InputMapProposal] = Field(default_factory=list)     # capability/human input field sources
    read_only_inputs: List[ReadOnlyInputProposal] = Field(default_factory=list)
    confidence: float = 1.0
    rationale: Optional[str] = None


class TriageRuleProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rule_id: str = "triage"
    priority: int = 100
    description: Optional[str] = None
    when: Dict[str, Any] = Field(default_factory=dict)                  # predicate tree (all/any/not + {field,op,value})
    confidence: float = 0.4
    rationale: Optional[str] = None


class CopilotProposal(BaseModel):
    """The whole semantic proposal for a pack: per-element decisions + pack-level trigger/triage + a summary."""
    model_config = ConfigDict(extra="ignore")
    summary: str = ""                            # plain-language process narrative (feeds the report)
    elements: List[ElementProposal] = Field(default_factory=list)
    trigger_schema: Optional[Dict[str, Any]] = None
    trigger_confidence: float = 0.4
    triage_rules: List[TriageRuleProposal] = Field(default_factory=list)

    def by_element(self) -> Dict[str, ElementProposal]:
        return {e.element_id: e for e in self.elements}
