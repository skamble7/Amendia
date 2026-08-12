# app/models/cohort.py
"""ADR-063 Phase 2 — cohort DEFINITION (design-time), registered/queried in the process-registry.

A definition declares the correlation contract and the external end-of-process (close) message schema. A pack's
``cohort_membership`` points at one by ``cohort_def_id``. The registry owns close-schema knowledge, so it — not
the ingestor — classifies inbound close messages (folded into ``/resolve``). The cohort INSTANCE SoR lives in
agent-runtime (Phase 1); this is only the definition.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from amendia_contracts.common import utcnow

# --------------------------------------------------------------------------- #
# ADR-064 P1 — the expectation graph (a DAG on the definition) + SLA specs.
# Additive + optional: a definition with NO expectation_graph behaves exactly as ADR-063 (pure observer).
# --------------------------------------------------------------------------- #

# Synthetic (reserved) node ids. Segment nodes are keyed by the member's pack_key and may never use these.
START_NODE = "__start__"   # the cohort opens on its first member
CLOSE_NODE = "__close__"   # the external end-of-process (close) message

NodeType = Literal["expected", "conditional"]     # expected → always runs; conditional → only on some XOR path
SplitType = Literal["and", "xor"]                 # classification of a node's out-edge set
Moment = Literal["arrival", "completion"]         # observable moments of a segment node
SlaClock = Literal["wall", "business"]            # wall-clock vs business-hours calendar
SlaOwner = Literal["external", "amendia", "shared"]   # accountability attribution


class EdgeSla(BaseModel):
    """A time promise on an edge: after ``anchor_moment`` of the edge's ``from`` node (cohort-open when
    from == __start__), expect ``satisfy_moment`` of the ``to`` node (close-received when to == __close__)
    within ``deadline_seconds``. Numeric well-formedness is checked at register/update time."""
    anchor_moment: Moment = "completion"
    satisfy_moment: Moment = "arrival"
    deadline_seconds: int
    at_risk_seconds: int = 0
    clock: SlaClock = "wall"
    owner: SlaOwner


class NodeSla(BaseModel):
    """A segment's own runtime (arrival → completion) promise — conventionally owned by ``amendia``."""
    deadline_seconds: int
    at_risk_seconds: int = 0
    clock: SlaClock = "wall"
    owner: SlaOwner = "amendia"


class CohortNode(BaseModel):
    node_id: str                                  # a segment pack_key (unique; never a reserved id)
    node_type: NodeType = "expected"
    runtime_sla: Optional[NodeSla] = None


class CohortEdge(BaseModel):
    from_node: str                                # a node_id or __start__
    to_node: str                                  # a node_id or __close__
    split: SplitType                              # classification of from_node's out-edge set (validated consistent)
    sla: Optional[EdgeSla] = None


class EndToEndSla(BaseModel):
    """The whole-case promise (cohort-open → cohort-close), conventionally ``shared``."""
    deadline_seconds: int
    at_risk_seconds: int = 0
    clock: SlaClock = "wall"
    owner: SlaOwner = "shared"


class ExpectationGraph(BaseModel):
    nodes: List[CohortNode] = Field(default_factory=list)
    edges: List[CohortEdge] = Field(default_factory=list)
    end_to_end_sla: Optional[EndToEndSla] = None


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
    # ADR-064 P1: optional timing-expectation DAG + SLA specs. None → ADR-063 behaviour (pure observer, no SLAs).
    expectation_graph: Optional[ExpectationGraph] = None


class CohortDefinitionCreate(CohortDefinitionBase):
    """Register-request body (no store timestamps)."""


class CohortDefinitionUpdate(BaseModel):
    """Inline-edit request body — the MUTABLE fields only. ``cohort_def_id`` is immutable (instances + pack
    ``cohort_membership`` key on it), so it is never in the body; the path parameter identifies the target.
    Full-representation semantics (forward-only): omitting ``expectation_graph`` clears it, same as the other
    optional fields."""
    display_name: Optional[str] = None
    description: Optional[str] = None
    close_schema: Dict[str, Any]
    close_correlation_path: str
    close_outcome_path: Optional[str] = None
    expectation_graph: Optional[ExpectationGraph] = None


class CohortDefinition(CohortDefinitionBase):
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def to_doc(self) -> dict:
        return self.model_dump(mode="json")


class SetCohortMembershipRequest(BaseModel):
    """Assign a pack version to a cohort (ADR-063). ``correlation_key`` is a dotpath into THIS pack's trigger."""
    cohort_def_id: str
    correlation_key: str
