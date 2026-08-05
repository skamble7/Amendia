# app/readmodels.py
"""ADR-058 Phase C read-model assembly — pure functions over ClickHouse rows.

Kept free of I/O so they unit-test without a live store: the reader supplies rows from ``audit_events``
(decision-trail) and ``otel_traces`` + ``audit_events`` (lineage); these turn them into the renderable
shapes. Domain-neutral keys throughout; values are content (artifact keys, comments, rationale)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import orjson


# --------------------------------------------------------------------------- #
# Decision trail
# --------------------------------------------------------------------------- #
def _comment_from_payload(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        return payload.get("comment")
    if isinstance(payload, str) and payload:
        try:
            return orjson.loads(payload).get("comment")
        except Exception:  # noqa: BLE001
            return None
    return None


def _u8_to_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    return bool(v)


def _artifact_ref(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    if not row:
        return None
    return {"artifact_key": row.get("artifact_key", ""), "schema_ref": row.get("schema_ref", "")}


def build_decision_trail(decided_rows: List[Dict[str, Any]],
                         artifact_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entry per HITL decision (in occurred_at order), with the proposed (agent-drafted) and
    approved (human) artifact references for its element. The concrete values are fetched + diffed by
    the frontend (Phase E) — this returns references + metadata only (glea reads ClickHouse only)."""
    # Group the element's artifact commits into a capability side (proposed draft) and a human side
    # (approved output). Most gates commit once; then proposed == approved (same key, differing VALUES
    # the frontend diffs).
    by_element: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for a in artifact_rows:
        el = a.get("element_id", "")
        slot = by_element.setdefault(el, {})
        human = bool(a.get("authored_by_human")) or a.get("actor_kind") == "human"
        slot["human" if human else "capability"] = a

    trail: List[Dict[str, Any]] = []
    for d in decided_rows:
        el = d.get("element_id", "")
        arts = by_element.get(el, {})
        approved = arts.get("human") or arts.get("capability")
        proposed = arts.get("capability") or approved
        trail.append({
            "element_id": el,
            "decided_by": d.get("decided_by", ""),
            "role": d.get("role", ""),
            "decided_at": d.get("occurred_at"),
            "decision": d.get("decision", ""),
            "sod_satisfied": _u8_to_bool(d.get("sod_satisfied")),
            "comment": _comment_from_payload(d.get("payload")),
            "proposed": _artifact_ref(proposed),
            "approved": _artifact_ref(approved),
        })
    return trail


# --------------------------------------------------------------------------- #
# Lineage (artifact dataflow graph from span links)
# --------------------------------------------------------------------------- #
def build_lineage(trace_id: str, span_rows: List[Dict[str, Any]],
                  artifact_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Turn the Phase A span-link graph into a renderable artifact DAG. Nodes are producing spans (so
    MI iterations stay DISTINCT → the join fan-in is visible); each node carries its artifact identity.
    Edges are producer→consumer, from each span's links to the spans that produced its inputs."""
    # authored_by_human isn't a span attribute — enrich from the audit rows by artifact_key.
    authored: Dict[str, Optional[bool]] = {}
    for a in artifact_rows:
        ak = a.get("artifact_key", "")
        if ak:
            authored[ak] = _u8_to_bool(a.get("authored_by_human"))

    # A "producer" span is one that carries an artifact_key. Node id = span id.
    producers: Dict[str, Dict[str, Any]] = {}
    for s in span_rows:
        ak = s.get("artifact_key") or ""
        if not ak:
            continue
        sid = s.get("span_id", "")
        producers[sid] = {
            "span_id": sid,
            "element_id": s.get("element_id", ""),
            "artifact_key": ak,
            "schema_ref": s.get("schema_ref", ""),
            "actor_kind": s.get("actor_kind", ""),
            "authored_by_human": authored.get(ak),
        }

    edges: List[Dict[str, Any]] = []
    seen = set()
    for s in span_rows:
        to_sid = s.get("span_id", "")
        if to_sid not in producers:
            continue
        for from_sid in (s.get("link_span_ids") or []):
            if from_sid in producers and from_sid != to_sid:
                key = (from_sid, to_sid)
                if key in seen:
                    continue
                seen.add(key)
                edges.append({
                    "from_span": from_sid, "to_span": to_sid,
                    "from_artifact_key": producers[from_sid]["artifact_key"],
                    "to_artifact_key": producers[to_sid]["artifact_key"],
                })

    return {
        "trace_id": trace_id,
        "nodes": list(producers.values()),
        "edges": edges,
    }


# --------------------------------------------------------------------------- #
# Aggregate tiles (Phase D) — pure shaping over ClickHouse aggregate results
# --------------------------------------------------------------------------- #
def _quant(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Shape a ``{p50, p95, count}`` quantile row, zeroing an empty/None result (never an error)."""
    row = row or {}
    return {
        "p50": float(row.get("p50") or 0.0),
        "p95": float(row.get("p95") or 0.0),
        "count": int(row.get("count") or 0),
    }


def build_metrics(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the metrics bundle from the reader's aggregate query results. Pure + defensive: any
    missing figure zeroes out. ``inputs`` keys: ``latency``/``duration`` (quantile rows),
    ``decisions`` (list of {decision, role, count}), ``four_eyes``/``egress_denied``/``sla_breaches``
    (ints), and optional ``outcome`` ({completed, failed}) for the platform-wide bundle."""
    decisions = []
    for d in inputs.get("decisions") or []:
        decisions.append({
            "decision": d.get("decision", "") or "",
            "role": d.get("role", "") or "",
            "count": int(d.get("count") or 0),
        })
    bundle: Dict[str, Any] = {
        "approval_latency_ms": _quant(inputs.get("latency")),
        "capability_duration_ms": _quant(inputs.get("duration")),
        "hitl_decisions": decisions,
        "four_eyes_enforced": int(inputs.get("four_eyes") or 0),
        "egress_denied": int(inputs.get("egress_denied") or 0),
        "sla_breaches": int(inputs.get("sla_breaches") or 0),
    }
    outcome = inputs.get("outcome")
    if outcome is not None:
        bundle["instances_by_outcome"] = {
            "completed": int(outcome.get("completed") or 0),
            "failed": int(outcome.get("failed") or 0),
        }
    return bundle


# --------------------------------------------------------------------------- #
# Trace tree (Phase E §6) — the instance's spans for the in-view waterfall
# --------------------------------------------------------------------------- #
def build_trace_tree(trace_id: str, span_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Shape the raw span rows into a renderable tree: each span keeps its parent link + a ``depth``
    (distance to a root within this trace) so the frontend can render an indented waterfall without
    re-deriving the hierarchy. Cycle/oprhan-safe (a missing parent → depth 0). Pure, unit-testable."""
    spans = []
    for s in span_rows:
        spans.append({
            "span_id": s.get("span_id", ""),
            "parent_span_id": s.get("parent_span_id", "") or "",
            "name": s.get("name", "") or "",
            "start_ns": int(s.get("start_ns") or 0),
            "duration_ns": int(s.get("duration_ns") or 0),
            "element_id": s.get("element_id", "") or "",
            "actor": s.get("actor", "") or "",
            "actor_kind": s.get("actor_kind", "") or "",
            "artifact_key": s.get("artifact_key", "") or "",
        })
    ids = {s["span_id"] for s in spans}
    parent_of = {s["span_id"]: s["parent_span_id"] for s in spans}

    def depth(sid: str) -> int:
        d, cur, seen = 0, sid, set()
        while True:
            p = parent_of.get(cur, "")
            if not p or p not in ids or p in seen:
                return d
            seen.add(cur)
            d += 1
            cur = p

    for s in spans:
        s["depth"] = depth(s["span_id"])
    # Root spans (no in-trace parent) sort first; children follow their start order (already sorted).
    return {"trace_id": trace_id, "spans": spans}
