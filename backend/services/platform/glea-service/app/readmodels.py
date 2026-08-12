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
            "_start": int(s.get("start_ns") or 0),  # tie-break for "prefer later"; not emitted
        }

    # Raw producer→consumer edges (a consumer's span links point at the spans that produced its inputs).
    raw_edges = []
    for s in span_rows:
        to_sid = s.get("span_id", "")
        if to_sid not in producers:
            continue
        for from_sid in (s.get("link_span_ids") or []):
            if from_sid in producers and from_sid != to_sid:
                raw_edges.append((from_sid, to_sid))

    # Dedupe duplicate producers of the same (element_id, artifact_key) — the HITL park+resume case
    # emits two spans for one logical artifact. A producer that is REFERENCED by a downstream edge is
    # the committing (resume) span; a park span never becomes a link target. So keep the referenced
    # producers (this preserves the MI fan-in — every iteration is referenced by the join) and drop
    # the unreferenced duplicates, re-pointing their edges. When none in a group is referenced
    # (a terminal artifact with no consumer), keep the latest.
    referenced = {f for f, _ in raw_edges}
    groups: Dict[tuple, List[str]] = {}
    for sid, node in producers.items():
        groups.setdefault((node["element_id"], node["artifact_key"]), []).append(sid)
    remap: Dict[str, str] = {}
    dropped: set = set()
    for sids in groups.values():
        if len(sids) < 2:
            continue
        keep = [s for s in sids if s in referenced] or [max(sids, key=lambda s: producers[s]["_start"])]
        rep = max(keep, key=lambda s: producers[s]["_start"])  # latest kept = the resume producer
        for s in sids:
            if s not in keep:
                remap[s] = rep
                dropped.add(s)

    nodes = [{k: v for k, v in producers[s].items() if k != "_start"}
             for s in producers if s not in dropped]

    edges: List[Dict[str, Any]] = []
    seen = set()
    for f0, t0 in raw_edges:
        f = remap.get(f0, f0)
        t = remap.get(t0, t0)
        if f == t or (f, t) in seen:
            continue
        seen.add((f, t))
        edges.append({
            "from_span": f, "to_span": t,
            "from_artifact_key": producers[f]["artifact_key"],
            "to_artifact_key": producers[t]["artifact_key"],
        })

    return {
        "trace_id": trace_id,
        "nodes": nodes,
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


# --------------------------------------------------------------------------- #
# ADR-063 Phase 3A — cohort read-models (pure functions over cohort_events + member audit rows).
#
# The cohort view is OBSERVABILITY-GRADE: it is derived from the fail-soft CohortLifecycleEvent stream, not the
# authoritative agent-runtime Mongo SoR. A dropped/late event only degrades this view; the runtime state stays
# correct. Member status/duration are JOINED from audit_events (the members' own DISPATCH_ACCEPTED /
# PROCESS_COMPLETED / PROCESS_FAILED), keyed by each member's correlation_id — one source of truth for outcomes.
# --------------------------------------------------------------------------- #
from datetime import datetime as _dt, timezone as _tz  # noqa: E402

from amendia_common.events import (  # noqa: E402
    DISPATCH_ACCEPTED, PROCESS_COMPLETED, PROCESS_FAILED,
)

_EPOCH = _dt(1970, 1, 1, tzinfo=_tz.utc)
_STATE_BY_OP = {"opened": "open", "closing": "closing", "closed": "closed"}


def _sort_key(r: Dict[str, Any]):
    return (r.get("occurred_at") or _EPOCH, r.get("event_id") or "")


def _index_member_outcomes(member_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """correlation_id → {started_at, ended_at, status, outcome} from the members' audit rows."""
    idx: Dict[str, Dict[str, Any]] = {}
    for r in member_rows:
        cid = r.get("correlation_id") or ""
        if not cid:
            continue
        e = idx.setdefault(cid, {"started_at": None, "ended_at": None, "status": "running", "outcome": None})
        kind, when = r.get("kind") or "", r.get("occurred_at")
        if kind == DISPATCH_ACCEPTED:
            if when is not None and (e["started_at"] is None or when < e["started_at"]):
                e["started_at"] = when
        elif kind == PROCESS_COMPLETED:
            e.update(status="done", ended_at=when, outcome=(r.get("outcome") or "completed"))
        elif kind == PROCESS_FAILED:
            e.update(status="failed", ended_at=when, outcome=(r.get("outcome") or "failed"))
    return idx


def _members_by_pid(rows_sorted: List[Dict[str, Any]], ops: set) -> Dict[str, Dict[str, Any]]:
    """distinct member_process_instance_id → its first cohort row, for rows whose op ∈ ops."""
    seen: Dict[str, Dict[str, Any]] = {}
    for r in rows_sorted:
        if r.get("op") in ops:
            pid = r.get("member_process_instance_id") or ""
            if pid and pid not in seen:
                seen[pid] = r
    return seen


def _rollup(members_by_pid: Dict[str, Dict[str, Any]], outcome_idx: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    roll = {"done": 0, "running": 0, "failed": 0}
    for row in members_by_pid.values():
        status = outcome_idx.get(row.get("member_correlation_id") or "", {}).get("status", "running")
        roll[status] = roll.get(status, 0) + 1
    return roll


def _identity(cohort_instance_id: str, rows_sorted: List[Dict[str, Any]]) -> Dict[str, Any]:
    ident = {"cohort_instance_id": cohort_instance_id, "cohort_def_id": "", "correlation_value": "",
             "state": "open", "opened_at": None, "closed_at": None, "outcome": None}
    for r in rows_sorted:                                   # ascending → last non-empty / latest state wins
        if r.get("cohort_def_id"):
            ident["cohort_def_id"] = r["cohort_def_id"]
        if r.get("correlation_value"):
            ident["correlation_value"] = r["correlation_value"]
        op = r.get("op")
        if op in _STATE_BY_OP:
            ident["state"] = _STATE_BY_OP[op]
        if op == "opened":
            ident["opened_at"] = r.get("occurred_at")
        if op == "closed":
            ident["closed_at"] = r.get("occurred_at")
        if op in ("closing", "closed") and r.get("close_outcome"):
            ident["outcome"] = r["close_outcome"]
    return ident


def _summary(cohort_instance_id: str, rows_sorted: List[Dict[str, Any]],
             outcome_idx: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    ident = _identity(cohort_instance_id, rows_sorted)
    members = _members_by_pid(rows_sorted, {"member_joined"})
    anomalies = sum(1 for r in rows_sorted if r.get("op") == "late_join")
    return {**ident, "member_count": len(members), "rollup": _rollup(members, outcome_idx), "anomalies": anomalies}


# --------------------------------------------------------------------------- #
# ADR-064 P3 — cohort SLA read-models (pure functions over cohort_sla_events rows).
#
# Observability-grade: derived from the emitted CohortSlaEvent transitions (at_risk/breached/satisfied/voided),
# NOT the authoritative agent-runtime snapshot SoR — so still-`pending` expectations that never transitioned are
# not here (that is correct for a who-was-late accountability view; a full pending-plan view is a P4 follow-up
# that would need the runtime snapshot over REST). Current state of an expectation = the LATEST event by
# (occurred_at, event_id): states are monotonic (pending→at_risk→breached/satisfied/voided), so latest wins;
# owner/kind/ref/clock are stable per sla_id.
# --------------------------------------------------------------------------- #
_SLA_OWNERS = ("external", "amendia", "shared")


def _s(v: Any) -> str:
    return str(v) if v is not None else ""


def current_sla_states(sla_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The current state per sla_id (latest event wins), sorted by sla_id. Empty ISO time strings → None."""
    latest: Dict[str, tuple] = {}
    for r in sla_rows:
        sid = _s(r.get("sla_id"))
        if not sid:
            continue
        key = (r.get("occurred_at") or _EPOCH, _s(r.get("event_id")))
        if sid not in latest or key > latest[sid][0]:
            latest[sid] = (key, r)
    entries = [{
        "sla_id": sid,
        "kind": _s(r.get("kind")),
        "ref": _s(r.get("ref")),
        "owner": _s(r.get("owner")),
        "clock": _s(r.get("clock")),
        "state": _s(r.get("state")),
        "due_at": _s(r.get("due_at")) or None,
        "at_risk_at": _s(r.get("at_risk_at")) or None,
        "detected_at": _s(r.get("detected_at")) or None,
    } for sid, (_, r) in latest.items()]
    entries.sort(key=lambda e: e["sla_id"])
    return entries


def sla_summary(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Owner-attributed breach rollup + at_risk/satisfied/voided counts, over the CURRENT state per sla_id."""
    breaches = {o: 0 for o in _SLA_OWNERS}
    breaches["total"] = 0
    at_risk = satisfied = voided = 0
    for e in entries:
        st = e["state"]
        if st == "breached":
            if e["owner"] in breaches:
                breaches[e["owner"]] += 1
            breaches["total"] += 1
        elif st == "at_risk":
            at_risk += 1
        elif st == "satisfied":
            satisfied += 1
        elif st == "voided":
            voided += 1
    return {"states": entries, "breaches": breaches, "at_risk": at_risk,
            "satisfied": satisfied, "voided": voided}


def build_sla_section(sla_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The cohort-detail ``sla`` section for one cohort's SLA event rows (empty when there are none)."""
    return sla_summary(current_sla_states(sla_rows))


def build_cohort_list(cohort_rows: List[Dict[str, Any]],
                      member_outcome_rows: List[Dict[str, Any]],
                      sla_rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """One summary per cohort_instance_id (newest opened first): identity, state, member_count, the
    done/running/failed rollup joined from member outcomes, opened/closed_at, close outcome, anomaly count, and
    (ADR-064 P3) the compact SLA badges ``sla_breaches``/``sla_at_risk`` (0 when the cohort has no SLA events)."""
    outcome_idx = _index_member_outcomes(member_outcome_rows)
    by_cohort: Dict[str, List[Dict[str, Any]]] = {}
    for r in cohort_rows:
        by_cohort.setdefault(r.get("cohort_instance_id") or "", []).append(r)
    sla_by_cohort: Dict[str, List[Dict[str, Any]]] = {}
    for r in (sla_rows or []):
        sla_by_cohort.setdefault(r.get("cohort_instance_id") or "", []).append(r)
    out = []
    for cid, rows in by_cohort.items():
        if not cid:
            continue
        summary = _summary(cid, sorted(rows, key=_sort_key), outcome_idx)
        sla = build_sla_section(sla_by_cohort.get(cid, []))
        summary["sla_breaches"] = sla["breaches"]["total"]
        summary["sla_at_risk"] = sla["at_risk"]
        out.append(summary)
    out.sort(key=lambda c: (c["opened_at"] or _EPOCH), reverse=True)
    return out


def build_cohort_detail(cohort_rows_for_one: List[Dict[str, Any]],
                        member_outcome_rows: List[Dict[str, Any]],
                        sla_rows: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """Identity + roster (each member with its joined status/duration/outcome) + the ordered lifecycle event
    stream + a close summary + (ADR-064 P3) the ``sla`` section (per-SLA current state + owner-attributed
    counts; empty when the cohort has no SLA events). None when there are no rows for the cohort."""
    if not cohort_rows_for_one:
        return None
    rows_sorted = sorted(cohort_rows_for_one, key=_sort_key)
    cohort_instance_id = next((r.get("cohort_instance_id") for r in rows_sorted if r.get("cohort_instance_id")), "")
    outcome_idx = _index_member_outcomes(member_outcome_rows)
    summary = _summary(cohort_instance_id, rows_sorted, outcome_idx)

    roster: List[Dict[str, Any]] = []
    seen: set = set()
    for r in rows_sorted:
        op = r.get("op")
        if op not in ("member_joined", "late_join"):
            continue
        pid = r.get("member_process_instance_id") or ""
        if not pid or pid in seen:
            continue
        seen.add(pid)
        o = outcome_idx.get(r.get("member_correlation_id") or "", {})
        roster.append({
            "process_instance_id": pid,
            "pack_key": r.get("member_pack_key") or "",
            "pack_version": r.get("member_pack_version") or "",
            "correlation_id": r.get("member_correlation_id") or "",
            "status": o.get("status", "running"),
            "started_at": o.get("started_at"),
            "ended_at": o.get("ended_at"),
            "outcome": o.get("outcome"),
            "late": op == "late_join",
        })

    events = [{"op": r.get("op") or "", "at": r.get("occurred_at"),
               "process_instance_id": r.get("member_process_instance_id") or None,
               "detail": r.get("detail") or None} for r in rows_sorted]
    close = {"signalled": summary["state"] in ("closing", "closed"),
             "outcome": summary["outcome"], "state": summary["state"], "late_joins": summary["anomalies"]}
    sla = build_sla_section(sla_rows or [])
    return {**summary, "roster": roster, "events": events, "close": close, "sla": sla}
