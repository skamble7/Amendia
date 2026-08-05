# app/routers/audit.py
"""Per-instance audit read API (ADR-058 Phase B — the query foundation; decision-trail + lineage
read-models are Phase C)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query

from app.clickhouse.client import StorageUnavailable
from app.clickhouse.reader import AuditReader
from app.clickhouse.sealer import AuditSealer
from app.deps import get_reader, get_sealer
from app.models.audit import (
    AuditEventOut,
    DecisionTrailOut,
    InstanceAuditOut,
    LineageOut,
    MetricsBundleOut,
    MetricsWindow,
    TraceTreeOut,
)
from app.readmodels import build_decision_trail, build_lineage, build_metrics, build_trace_tree

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["audit"])


def _to_out(row: Dict[str, Any]) -> AuditEventOut:
    payload = row.get("payload")
    if isinstance(payload, str) and payload:
        try:
            payload = orjson.loads(payload)
        except Exception:  # noqa: BLE001
            payload = {"_raw": payload}
    data = {**row, "payload": payload}
    return AuditEventOut(**data)


@router.get("/instances/{correlation_id}", response_model=InstanceAuditOut)
async def instance_audit(correlation_id: str, reader: AuditReader = Depends(get_reader)):
    """The instance's audit events in ``occurred_at`` order (append-only, deduped by ``event_id``)."""
    try:
        rows = await reader.instance_events(correlation_id)
    except StorageUnavailable as exc:
        logger.warning("audit read failed for %s: %s", correlation_id, exc)
        raise HTTPException(status_code=503, detail="audit store unavailable") from exc
    events = [_to_out(r) for r in rows]
    return InstanceAuditOut(correlation_id=correlation_id, count=len(events), events=events)


@router.get("/instances/{correlation_id}/decision-trail", response_model=DecisionTrailOut)
async def decision_trail(correlation_id: str, reader: AuditReader = Depends(get_reader)):
    """The ordered HITL gate decisions for the run — decided_by/role/decision/sod_satisfied/comment +
    the proposed (agent-drafted) and approved (human) artifact references. References + metadata only;
    the frontend fetches/diffs the concrete values (Phase E)."""
    try:
        decided = await reader.decided_rows(correlation_id)
        artifacts = await reader.artifact_rows(correlation_id)
    except StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="audit store unavailable") from exc
    gates = build_decision_trail(decided, artifacts)
    return DecisionTrailOut(correlation_id=correlation_id, count=len(gates), gates=gates)


@router.get("/instances/{correlation_id}/lineage", response_model=LineageOut)
async def lineage(correlation_id: str, reader: AuditReader = Depends(get_reader)):
    """The artifact dataflow DAG for the run, assembled from the Phase A span links in otel_traces
    (nodes = producing spans with their artifact identity; edges = producer→consumer). Includes the MI
    join fan-in. Pure ClickHouse read."""
    try:
        trace_id = await reader.trace_id_for(correlation_id)
        spans = await reader.trace_spans(trace_id) if trace_id else []
        artifacts = await reader.artifact_rows(correlation_id)
    except StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="audit store unavailable") from exc
    graph = build_lineage(trace_id, spans, artifacts)
    return LineageOut(correlation_id=correlation_id, **graph)


@router.get("/instances/{correlation_id}/seal")
async def seal_verification(correlation_id: str, sealer: AuditSealer = Depends(get_sealer)):
    """Recompute the hash-chain for the instance and report intact/broken (ADR-058 tamper-evidence).
    Returns ``{rows, sealed, intact, broken_event_id}`` — ``intact`` false ⇒ a sealed row was mutated."""
    try:
        return await sealer.verify_correlation(correlation_id)
    except StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="audit store unavailable") from exc


@router.get("/instances/{correlation_id}/trace", response_model=TraceTreeOut)
async def trace_tree(correlation_id: str, reader: AuditReader = Depends(get_reader)):
    """The instance's spans for the in-view execution waterfall (ADR-058 §6) — each span with its
    parent link + depth + the amendia.* attrs. Pure otel_traces read (same pattern as lineage)."""
    try:
        trace_id = await reader.trace_id_for(correlation_id)
        spans = await reader.trace_tree(trace_id) if trace_id else []
    except StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="audit store unavailable") from exc
    tree = build_trace_tree(trace_id, spans)
    return TraceTreeOut(correlation_id=correlation_id, **tree)


@router.get("/instances/{correlation_id}/metrics", response_model=MetricsBundleOut)
async def instance_metrics(correlation_id: str, reader: AuditReader = Depends(get_reader)):
    """The per-instance aggregate tiles (ADR-058 Phase D) — approval-latency + capability-exec-duration
    quantiles, HITL decisions by decision+role, four-eyes-enforced / egress-denied / SLA-breach counts.
    Every figure is a ClickHouse aggregation scoped to this correlation_id; an empty instance zeroes out."""
    try:
        inputs = await reader.metrics_inputs(correlation_id=correlation_id)
    except StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="audit store unavailable") from exc
    return MetricsBundleOut(correlation_id=correlation_id, **build_metrics(inputs))


@router.get("/metrics", response_model=MetricsBundleOut)
async def platform_metrics(
    since: Optional[datetime] = Query(None, description="window start (default: 30d ago)"),
    until: Optional[datetime] = Query(None, description="window end (default: now)"),
    reader: AuditReader = Depends(get_reader),
):
    """Platform-wide aggregates over a time window (ADR-058 Phase D §2) — the SAME figures as the
    per-instance bundle (built from the same query builders, correlation_id predicate dropped) plus
    instances-by-outcome. Thin foundation for the deferred cross-instance console; no UI consumes it yet."""
    until = until or datetime.now(timezone.utc)
    since = since or (until - timedelta(days=30))
    try:
        inputs = await reader.metrics_inputs(since=since, until=until)
    except StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="audit store unavailable") from exc
    return MetricsBundleOut(window=MetricsWindow(since=since, until=until), **build_metrics(inputs))
