# app/models/audit.py
"""Read-API response model for a per-instance audit event (ADR-058 Phase B)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    event_id: str
    occurred_at: datetime
    ingested_at: Optional[datetime] = None
    kind: str
    correlation_id: str
    trace_id: str
    actor: str = ""
    actor_kind: str = ""
    role: str = ""
    element_id: str = ""
    pack_key: str = ""
    pack_version: str = ""
    decision: str = ""
    decided_by: str = ""
    sod_satisfied: Optional[bool] = None
    artifact_key: str = ""
    schema_ref: str = ""
    authored_by_human: Optional[bool] = None
    egress_host: str = ""
    egress_decision: str = ""
    payload: Optional[Dict[str, Any]] = None


class InstanceAuditOut(BaseModel):
    correlation_id: str
    count: int
    events: list[AuditEventOut]


# --- Phase C read-models ---------------------------------------------------- #
class ArtifactRef(BaseModel):
    artifact_key: str = ""
    schema_ref: str = ""


class DecisionTrailEntry(BaseModel):
    element_id: str
    decided_by: str = ""
    role: str = ""
    decided_at: Optional[datetime] = None
    decision: str = ""
    sod_satisfied: Optional[bool] = None
    comment: Optional[str] = None
    proposed: Optional[ArtifactRef] = None
    approved: Optional[ArtifactRef] = None


class DecisionTrailOut(BaseModel):
    correlation_id: str
    count: int
    gates: list[DecisionTrailEntry]


class LineageNode(BaseModel):
    span_id: str
    element_id: str = ""
    artifact_key: str = ""
    schema_ref: str = ""
    actor_kind: str = ""
    authored_by_human: Optional[bool] = None


class LineageEdge(BaseModel):
    from_span: str
    to_span: str
    from_artifact_key: str = ""
    to_artifact_key: str = ""


class LineageOut(BaseModel):
    correlation_id: str
    trace_id: str = ""
    nodes: list[LineageNode]
    edges: list[LineageEdge]


# --- Phase D aggregate tiles ------------------------------------------------ #
class Quantiles(BaseModel):
    p50: float = 0.0
    p95: float = 0.0
    count: int = 0


class DecisionCount(BaseModel):
    decision: str = ""
    role: str = ""
    count: int = 0


class OutcomeCounts(BaseModel):
    completed: int = 0
    failed: int = 0


class MetricsWindow(BaseModel):
    since: Optional[datetime] = None
    until: Optional[datetime] = None


class MetricsBundleOut(BaseModel):
    correlation_id: Optional[str] = None
    window: Optional[MetricsWindow] = None
    approval_latency_ms: Quantiles
    capability_duration_ms: Quantiles
    hitl_decisions: list[DecisionCount]
    four_eyes_enforced: int = 0
    egress_denied: int = 0
    sla_breaches: int = 0
    instances_by_outcome: Optional[OutcomeCounts] = None


# --- Phase E §6 trace tree -------------------------------------------------- #
class TraceSpanOut(BaseModel):
    span_id: str
    parent_span_id: str = ""
    name: str = ""
    start_ns: int = 0
    duration_ns: int = 0
    depth: int = 0
    element_id: str = ""
    actor: str = ""
    actor_kind: str = ""
    artifact_key: str = ""


class TraceTreeOut(BaseModel):
    correlation_id: str
    trace_id: str = ""
    spans: list[TraceSpanOut]
