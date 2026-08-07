# app/events/mapper.py
"""Project a governed event (routing key + JSON body) onto an ``audit_events`` row.

Domain-neutral by construction: the mapper reads only STRUCTURAL keys (the ADR-058 conventions) and
stores the full event body in the ``payload`` JSON column — it never interprets a business field. The
row ``kind`` is the event-name segment of the routing key (``<service>.<kind>.<version>``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import orjson

from amendia_common.events import EGRESS_DECISION


class UnmappableEvent(ValueError):
    """The message lacks the minimum audit envelope (event_id / occurred_at) — a poison message the
    consumer drops (reject, no requeue), never persists."""


def event_kind(routing_key: str) -> str:
    """The ``<kind>`` segment of ``<service>.<kind>.<version>`` (second-to-last dotted part)."""
    parts = (routing_key or "").split(".")
    return parts[-2] if len(parts) >= 2 else (routing_key or "unknown")


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        # to_doc() emits ISO-8601 (…+00:00). Accept a trailing 'Z' defensively.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise UnmappableEvent("occurred_at missing/invalid")


def _u8(value: Any) -> Optional[int]:
    if value is None:
        return None
    return 1 if bool(value) else 0


def to_row(routing_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict) or not payload.get("event_id"):
        raise UnmappableEvent("event_id missing")
    trace = payload.get("trace") or {}
    kind = event_kind(routing_key)
    is_egress = kind == EGRESS_DECISION
    return {
        "event_id": str(payload["event_id"]),
        "occurred_at": _parse_dt(payload.get("occurred_at")),
        "kind": kind,
        # correlation_id lives on the nested Trace; fall back to trigger_id (its canonical value).
        "correlation_id": str(trace.get("correlation_id") or payload.get("trigger_id") or ""),
        "trace_id": str(trace.get("trace_id") or ""),
        "actor": str(payload.get("actor") or payload.get("decided_by") or ""),
        "actor_kind": str(payload.get("actor_kind") or ""),
        "role": str(payload.get("role") or ""),
        "element_id": str(payload.get("element_id") or ""),
        "pack_key": str(payload.get("pack_key") or ""),
        # pack_lifecycle names it `version`; everything else `pack_version`.
        "pack_version": str(payload.get("pack_version") or payload.get("version") or ""),
        # A HITL/decision `decision` goes to the decision column; an egress allow/deny goes to
        # egress_decision (kept distinct so governance queries don't conflate them).
        "decision": "" if is_egress else str(payload.get("decision") or ""),
        "decided_by": str(payload.get("decided_by") or ""),
        "sod_satisfied": _u8(payload.get("sod_satisfied")),
        # ArtifactCommittedEvent carries artifact_key; the decision-trail + lineage read-models join on
        # it. Other kinds leave "".
        "artifact_key": str(payload.get("artifact_key") or ""),
        "schema_ref": str(payload.get("schema_ref") or ""),
        "authored_by_human": _u8(payload.get("authored_by_human")),
        "egress_host": str(payload.get("host") or "") if is_egress else "",
        "egress_decision": str(payload.get("decision") or "") if is_egress else "",
        "payload": orjson.dumps(payload).decode("utf-8"),
    }
