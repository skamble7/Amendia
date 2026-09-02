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

from amendia_common.events import COHORT_LIFECYCLE, COHORT_SLA, EGRESS_DECISION, PACK_LIFECYCLE

# ADR-065 P4b: the derived audit-row kind for a single side-effect waiver (fanned out from a publish
# PackLifecycleEvent). A new `kind` VALUE only — no new column and no new routing key.
PACK_WAIVER_KIND = "pack_waiver"


class UnmappableEvent(ValueError):
    """The message lacks the minimum audit envelope (event_id / occurred_at) — a poison message the
    consumer drops (reject, no requeue), never persists."""


def event_kind(routing_key: str) -> str:
    """The ``<kind>`` segment of ``<service>.<kind>.<version>`` (second-to-last dotted part)."""
    parts = (routing_key or "").split(".")
    return parts[-2] if len(parts) >= 2 else (routing_key or "unknown")


def is_cohort_event(routing_key: str) -> bool:
    """ADR-063 Phase 3A: a CohortLifecycleEvent (→ cohort_events, its own table)."""
    return event_kind(routing_key) == COHORT_LIFECYCLE


def is_cohort_sla_event(routing_key: str) -> bool:
    """ADR-064 P3: a CohortSlaEvent (→ cohort_sla_events, its own table)."""
    return event_kind(routing_key) == COHORT_SLA


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


def waiver_rows(routing_key: str, payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    """ADR-065 P4b: fan a publish ``PackLifecycleEvent``'s ``waivers`` out to one ``pack_waiver`` audit row EACH,
    so an auditor finds every ungated-real-world-action binding across packs by ``kind = 'pack_waiver'`` — with
    ``pack_key`` / ``pack_version`` / ``element_id`` / ``actor`` (= the justification's author) as real columns,
    and the capability / justification / timestamp / publisher on the row's own ``payload`` (JSONExtract-able,
    no cross-row scan). One blob per pack would have forced exactly that scan; one row per waiver does not.

    The derived rows share the lifecycle event's ``correlation_id`` (empty for registry events — they carry no
    Trace) and get a DETERMINISTIC ``event_id`` (``<event_id>:waiver:<element_id>``) so an at-least-once
    redelivery collapses on the ReplacingMergeTree key instead of double-counting."""
    if event_kind(routing_key) != PACK_LIFECYCLE:
        return []
    waivers = payload.get("waivers")
    if not isinstance(waivers, list) or not waivers:
        return []
    base_id = str(payload.get("event_id") or "")
    occurred = _parse_dt(payload.get("occurred_at"))
    trace = payload.get("trace") or {}
    correlation_id = str(trace.get("correlation_id") or "")
    trace_id = str(trace.get("trace_id") or "")
    publisher = str(payload.get("actor") or "")
    pack_key = str(payload.get("pack_key") or "")
    pack_version = str(payload.get("version") or payload.get("pack_version") or "")
    rows: list[Dict[str, Any]] = []
    for w in waivers:
        if not isinstance(w, dict) or not w.get("element_id"):
            continue
        element_id = str(w["element_id"])
        rows.append({
            "event_id": f"{base_id}:waiver:{element_id}",
            "occurred_at": occurred,
            "kind": PACK_WAIVER_KIND,
            "correlation_id": correlation_id,
            "trace_id": trace_id,
            "actor": str(w.get("waived_by") or ""),      # the JUSTIFICATION's author — "who allowed it"
            "actor_kind": "human",
            "role": "",
            "element_id": element_id,
            "pack_key": pack_key,
            "pack_version": pack_version,
            "decision": "", "decided_by": "", "sod_satisfied": None,
            "artifact_key": "", "schema_ref": "", "authored_by_human": None,
            "egress_host": "", "egress_decision": "",
            "payload": orjson.dumps({
                "element_id": element_id,
                "capability_id": w.get("capability_id") or "",
                "justification": w.get("justification") or "",
                "waived_by": w.get("waived_by"),
                "waived_at": w.get("waived_at"),
                "publisher": publisher,                  # the pack's PUBLISHER — a different fact from waived_by
            }).decode("utf-8"),
        })
    return rows


def to_cohort_row(routing_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """ADR-063 Phase 3A: project a ``CohortLifecycleEvent`` payload onto a ``cohort_events`` row. Structural
    only. ``member_*`` come from the event's ``process_instance_id``/``pack_key``/``pack_version`` and its
    ``trace.correlation_id`` (the member instance's correlation_id — the join key into ``audit_events`` for the
    rollup; empty on ``opened``/``closing``/``closed``)."""
    if not isinstance(payload, dict) or not payload.get("event_id"):
        raise UnmappableEvent("event_id missing")
    if not payload.get("cohort_instance_id"):
        raise UnmappableEvent("cohort_instance_id missing")
    trace = payload.get("trace") or {}
    return {
        "event_id": str(payload["event_id"]),
        "occurred_at": _parse_dt(payload.get("occurred_at")),
        "op": str(payload.get("op") or ""),
        "cohort_instance_id": str(payload["cohort_instance_id"]),
        "cohort_def_id": str(payload.get("cohort_def_id") or ""),
        "correlation_value": str(payload.get("correlation_value") or ""),
        "member_process_instance_id": str(payload.get("process_instance_id") or ""),
        "member_pack_key": str(payload.get("pack_key") or ""),
        "member_pack_version": str(payload.get("pack_version") or ""),
        "member_correlation_id": str(trace.get("correlation_id") or ""),
        "close_outcome": str(payload.get("close_outcome") or ""),
        "detail": str(payload.get("detail") or ""),
        "trace_id": str(trace.get("trace_id") or ""),
    }


def to_cohort_sla_row(routing_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """ADR-064 P3: project a ``CohortSlaEvent`` payload onto a ``cohort_sla_events`` row. Structural only.
    ``due_at``/``at_risk_at``/``detected_at`` are kept as the emitted ISO strings ("" when absent) — lossless
    and parse-free for the observability view. Requires event_id + cohort_instance_id + sla_id (the row key)."""
    if not isinstance(payload, dict) or not payload.get("event_id"):
        raise UnmappableEvent("event_id missing")
    if not payload.get("cohort_instance_id"):
        raise UnmappableEvent("cohort_instance_id missing")
    if not payload.get("sla_id"):
        raise UnmappableEvent("sla_id missing")
    return {
        "event_id": str(payload["event_id"]),
        "occurred_at": _parse_dt(payload.get("occurred_at")),
        "state": str(payload.get("state") or ""),
        "cohort_instance_id": str(payload["cohort_instance_id"]),
        "cohort_def_id": str(payload.get("cohort_def_id") or ""),
        "correlation_value": str(payload.get("correlation_value") or ""),
        "sla_id": str(payload["sla_id"]),
        "kind": str(payload.get("kind") or ""),
        "ref": str(payload.get("ref") or ""),
        "owner": str(payload.get("owner") or ""),
        "clock": str(payload.get("clock") or ""),
        "due_at": str(payload.get("due_at") or ""),
        "at_risk_at": str(payload.get("at_risk_at") or ""),
        "detected_at": str(payload.get("detected_at") or ""),
    }
