# app/services/cohort_sla_service.py
"""ADR-064 Phase 2 — cohort SLA runtime: schedule, cancel-on-satisfy, void, fire-and-flag.

Sibling of :class:`CohortService` (which stays the pure ADR-063 observer). ``CohortService`` calls the four
hooks here fail-soft; this service materialises durable timers from the OPEN-time snapshot, resolves them as
the satisfying events arrive, and (via the poller's ``fire_due``) evaluates any that come due into
``at_risk``/``breached`` — exactly-once, crash-safe, attributed. It has an injectable ``now`` so every test is
deterministic with no sleeps. Zero execution authority: it only reads state and emits — never touches a member.

The SLA primitive: *after an anchor moment, expect a satisfying moment within a deadline; else breach, owned by
external/amendia/shared.* Anchors are captured by WHEN we schedule (open / arrival / completion); the satisfying
moment + node are stored on the expectation so the arrival/completion/close handlers can resolve it.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.dal.cohort_repo import CohortInstanceRepository
from app.dal.cohort_sla_repo import CohortSlaExpectationRepository, CohortSlaTimerRepository
from app.events.publisher import emit_cohort_sla
from app.models.cohort_instance import CohortInstance
from app.models.cohort_sla import (
    CohortSlaExpectation, CohortSlaTimer, SlaExpectationKind, SlaExpectationState, SlaMoment,
    SlaTimerPhase, SlaTimerStatus,
)
from app.services.business_clock import BusinessCalendar, add_business_seconds

logger = logging.getLogger(__name__)

START_NODE = "__start__"
CLOSE_NODE = "__close__"

# expectation states that are still open to resolution / firing
_OPEN = [SlaExpectationState.PENDING, SlaExpectationState.AT_RISK]
# fully-done: a satisfy/void already won — skip entirely. A BREACHED expectation is NOT here: a late
# satisfy/void must still fall through to record ``arrived_late`` (the breach stands; attribution keeps truth).
_RESOLVED = {SlaExpectationState.SATISFIED, SlaExpectationState.VOIDED}
_TERMINAL = {SlaExpectationState.SATISFIED, SlaExpectationState.VOIDED, SlaExpectationState.BREACHED}


def _real_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CohortSlaService:
    def __init__(
        self, *, exp_repo: CohortSlaExpectationRepository, timer_repo: CohortSlaTimerRepository,
        cohort_repo: CohortInstanceRepository, registry_client, publisher,
        calendar: Optional[BusinessCalendar] = None, now: Callable[[], datetime] = _real_utc_now,
    ) -> None:
        self._exp = exp_repo
        self._timers = timer_repo
        self._cohorts = cohort_repo
        self._registry = registry_client
        self._publisher = publisher
        self._calendar = calendar or BusinessCalendar()
        self._now = now

    def now(self) -> datetime:
        return self._now()

    # ------------------------------------------------------------------ #
    # Hooks driven by CohortService (fail-soft at the call site)
    # ------------------------------------------------------------------ #
    async def on_cohort_open(self, cohort: CohortInstance) -> None:
        """First member opened the cohort → snapshot the definition's expectation_graph (forward-only) and
        schedule every START-anchored edge SLA + the end-to-end SLA (both anchored to ``opened_at``). No graph
        (or fetch fails) → no snapshot, no timers: the cohort runs exactly as ADR-063."""
        graph = await self._fetch_graph(cohort.cohort_def_id)
        if graph is None:
            return
        await self._cohorts.set_sla_snapshot(cohort.cohort_instance_id, graph)
        # The cohort-open instant on the injected clock (== opened_at within ms in production; deterministic
        # in tests). START-anchored edges + the end-to-end SLA both measure from here.
        anchor = self._now()
        for e in _edges(graph):
            if e.get("from_node") == START_NODE and e.get("sla"):
                await self._schedule_edge(cohort, e, anchor)
        e2e = graph.get("end_to_end_sla")
        if e2e:
            await self._schedule_e2e(cohort, e2e, anchor)

    async def on_member_arrival(self, cohort_instance_id: str, node_id: str) -> None:
        """A member spawned (node ``node_id`` ARRIVED). Satisfy any arrival expectation targeting it; void the
        arrival expectations of its XOR siblings; schedule its runtime NodeSla and any arrival-anchored edges."""
        cohort = await self._cohorts.get(cohort_instance_id)
        graph = _snapshot(cohort)
        if graph is None:
            return
        now = self._now()
        await self._resolve_moment(cohort, node_id, SlaMoment.ARRIVAL, SlaExpectationState.SATISFIED, now)
        await self._void_xor_siblings(cohort, graph, node_id, now)
        node = _node(graph, node_id)
        if node and node.get("runtime_sla"):
            await self._schedule_node(cohort, node, now)
        for e in _edges(graph):
            if e.get("from_node") == node_id and e.get("sla") and _anchor_moment(e) == "arrival":
                await self._schedule_edge(cohort, e, now)

    async def on_member_completion(self, cohort_instance_id: str, node_id: str) -> None:
        """A member reached terminal (node ``node_id`` COMPLETED). Satisfy its runtime NodeSla + any
        completion expectation targeting it; schedule its completion-anchored (next-hop arrival) edges."""
        cohort = await self._cohorts.get(cohort_instance_id)
        graph = _snapshot(cohort)
        if graph is None:
            return
        now = self._now()
        await self._resolve_moment(cohort, node_id, SlaMoment.COMPLETION, SlaExpectationState.SATISFIED, now)
        for e in _edges(graph):
            if e.get("from_node") == node_id and e.get("sla") and _anchor_moment(e) == "completion":
                await self._schedule_edge(cohort, e, now)

    async def on_cohort_close(self, cohort_instance_id: str) -> None:
        """The external close message arrived (the CLOSE moment). Satisfy every close-satisfied expectation
        (end-to-end + any edge into __close__); void all still-pending expectations (the process ended, an
        outstanding arrival/completion is excused). An already-fired breach stands (resolve is CAS-guarded)."""
        cohort = await self._cohorts.get(cohort_instance_id)
        graph = _snapshot(cohort)
        if graph is None:
            return
        now = self._now()
        for exp in await self._exp.list_for_cohort(cohort_instance_id):
            if exp.state in _RESOLVED:
                continue
            if exp.satisfy_moment == SlaMoment.CLOSE:
                await self._resolve(cohort, exp, SlaExpectationState.SATISFIED, now)
            else:
                await self._resolve(cohort, exp, SlaExpectationState.VOIDED, now)

    # ------------------------------------------------------------------ #
    # Poller: fire due at-risk/breach rows (evaluate-and-flag, never resume)
    # ------------------------------------------------------------------ #
    async def fire_due(self, now: Optional[datetime] = None) -> int:
        now = now or self._now()
        fired = 0
        for timer in await self._timers.due(now):
            try:
                if await self._fire_one(timer, now):
                    fired += 1
            except Exception as exc:  # noqa: BLE001 — one bad SLA timer must not stall the poller
                logger.exception("cohort sla timer %s fire failed: %s", timer.sla_timer_id, exc)
        return fired

    async def _fire_one(self, timer: CohortSlaTimer, now: datetime) -> bool:
        won = await self._timers.mark(timer.sla_timer_id, SlaTimerStatus.FIRED)
        if won is None:
            return False  # already resolved (cancelled by satisfy/void, or fired) — once-only guard
        exp = await self._exp.get(timer.cohort_instance_id, timer.sla_id)
        if exp is None or exp.state in _TERMINAL:
            return False  # satisfy/void won the race, or a stale row — no-op
        if timer.phase == SlaTimerPhase.AT_RISK:
            updated = await self._exp.transition(
                exp.cohort_instance_id, exp.sla_id, expected=[SlaExpectationState.PENDING],
                new_state=SlaExpectationState.AT_RISK,
                stamps={"at_risk_marked_at": now, "detected_at": now},
            )
            if updated is None:
                return False
            await self._emit(updated, "at_risk", now)
            return True
        # breach phase
        updated = await self._exp.transition(
            exp.cohort_instance_id, exp.sla_id, expected=_OPEN,
            new_state=SlaExpectationState.BREACHED,
            stamps={"breached_at": now, "detected_at": now},
        )
        if updated is None:
            return False
        await self._emit(updated, "breached", now)
        return True

    # ------------------------------------------------------------------ #
    # scheduling
    # ------------------------------------------------------------------ #
    async def _schedule_edge(self, cohort: CohortInstance, edge: Dict[str, Any], anchor: datetime) -> None:
        sla = edge["sla"]
        to_node = edge["to_node"]
        satisfy_moment = (SlaMoment.CLOSE if to_node == CLOSE_NODE
                          else SlaMoment(sla.get("satisfy_moment", "arrival")))
        await self._register(
            cohort, sla_id=f"edge:{edge['from_node']}->{to_node}", kind=SlaExpectationKind.EDGE,
            ref=f"{edge['from_node']}->{to_node}", sla=sla, anchor=anchor,
            satisfy_node=to_node, satisfy_moment=satisfy_moment,
            split=edge.get("split"), from_node=edge.get("from_node"),
        )

    async def _schedule_node(self, cohort: CohortInstance, node: Dict[str, Any], anchor: datetime) -> None:
        await self._register(
            cohort, sla_id=f"node:{node['node_id']}", kind=SlaExpectationKind.NODE,
            ref=node["node_id"], sla=node["runtime_sla"], anchor=anchor,
            satisfy_node=node["node_id"], satisfy_moment=SlaMoment.COMPLETION,
        )

    async def _schedule_e2e(self, cohort: CohortInstance, sla: Dict[str, Any], anchor: datetime) -> None:
        await self._register(
            cohort, sla_id="e2e", kind=SlaExpectationKind.END_TO_END, ref=f"{START_NODE}->{CLOSE_NODE}",
            sla=sla, anchor=anchor, satisfy_node=CLOSE_NODE, satisfy_moment=SlaMoment.CLOSE,
        )

    async def _register(
        self, cohort: CohortInstance, *, sla_id: str, kind: SlaExpectationKind, ref: str,
        sla: Dict[str, Any], anchor: datetime, satisfy_node: str, satisfy_moment: SlaMoment,
        split: Optional[str] = None, from_node: Optional[str] = None,
    ) -> None:
        due_at, at_risk_at = self._deadlines(anchor, sla)
        exp = CohortSlaExpectation(
            sla_id=sla_id, cohort_instance_id=cohort.cohort_instance_id, cohort_def_id=cohort.cohort_def_id,
            correlation_value=cohort.correlation_value, kind=kind, ref=ref,
            owner=str(sla.get("owner")), clock=str(sla.get("clock", "wall")),
            satisfy_node=satisfy_node, satisfy_moment=satisfy_moment, split=split, from_node=from_node,
            anchor_at=anchor, due_at=due_at, at_risk_at=at_risk_at,
        )
        await self._exp.register(exp)  # idempotent — crash replay re-schedules to the same row
        await self._timers.register(CohortSlaTimer(
            sla_timer_id=f"slatmr-{uuid.uuid4().hex[:12]}", cohort_instance_id=cohort.cohort_instance_id,
            sla_id=sla_id, phase=SlaTimerPhase.BREACH, fire_at=due_at))
        if at_risk_at is not None:
            await self._timers.register(CohortSlaTimer(
                sla_timer_id=f"slatmr-{uuid.uuid4().hex[:12]}", cohort_instance_id=cohort.cohort_instance_id,
                sla_id=sla_id, phase=SlaTimerPhase.AT_RISK, fire_at=at_risk_at))

    def _deadlines(self, anchor: datetime, sla: Dict[str, Any]) -> Tuple[datetime, Optional[datetime]]:
        anchor = _as_utc(anchor)
        deadline = int(sla["deadline_seconds"])
        at_risk = int(sla.get("at_risk_seconds", 0) or 0)
        if str(sla.get("clock", "wall")) == "business":
            due_at = add_business_seconds(anchor, deadline, self._calendar)
            at_risk_at = add_business_seconds(anchor, at_risk, self._calendar) if 0 < at_risk < deadline else None
        else:
            due_at = anchor + timedelta(seconds=deadline)
            at_risk_at = anchor + timedelta(seconds=at_risk) if 0 < at_risk < deadline else None
        return due_at, at_risk_at

    # ------------------------------------------------------------------ #
    # cancel-on-satisfy / void
    # ------------------------------------------------------------------ #
    async def _resolve_moment(
        self, cohort: CohortInstance, node_id: str, moment: SlaMoment,
        resolution: SlaExpectationState, now: datetime,
    ) -> None:
        for exp in await self._exp.list_for_cohort(cohort.cohort_instance_id):
            if exp.state in _RESOLVED:
                continue
            if exp.satisfy_node == node_id and exp.satisfy_moment == moment:
                await self._resolve(cohort, exp, resolution, now)

    async def _void_xor_siblings(
        self, cohort: CohortInstance, graph: Dict[str, Any], arrived: str, now: datetime,
    ) -> None:
        """``arrived`` was reached by an XOR edge → the alternatives were not taken. Void the still-pending
        arrival expectations on its XOR siblings (the other targets of the same from_node's XOR out-set)."""
        froms = {e["from_node"] for e in _edges(graph)
                 if e.get("to_node") == arrived and e.get("split") == "xor"}
        if not froms:
            return
        sibling_ids = {
            f"edge:{e['from_node']}->{e['to_node']}"
            for e in _edges(graph)
            if e.get("from_node") in froms and e.get("split") == "xor"
            and e.get("to_node") != arrived and e.get("sla")
        }
        for exp in await self._exp.list_for_cohort(cohort.cohort_instance_id):
            if exp.sla_id in sibling_ids and exp.state not in _RESOLVED:
                await self._resolve(cohort, exp, SlaExpectationState.VOIDED, now)

    async def _resolve(
        self, cohort: CohortInstance, exp: CohortSlaExpectation,
        resolution: SlaExpectationState, now: datetime,
    ) -> None:
        stamp_field = "satisfied_at" if resolution == SlaExpectationState.SATISFIED else "voided_at"
        updated = await self._exp.transition(
            exp.cohort_instance_id, exp.sla_id, expected=_OPEN, new_state=resolution,
            stamps={stamp_field: now, "detected_at": now},
        )
        if updated is None:
            # Lost the race to a breach that already fired → the breach STANDS; record the late arrival.
            await self._exp.mark_arrived_late(exp.cohort_instance_id, exp.sla_id)
            return
        await self._timers.cancel_for_expectation(exp.cohort_instance_id, exp.sla_id)
        await self._emit(updated, resolution.value, now)

    # ------------------------------------------------------------------ #
    async def _emit(self, exp: CohortSlaExpectation, state: str, now: datetime) -> None:
        await emit_cohort_sla(
            self._publisher, state=state, cohort_def_id=exp.cohort_def_id,
            cohort_instance_id=exp.cohort_instance_id, correlation_value=exp.correlation_value,
            sla_id=exp.sla_id, kind=exp.kind.value, ref=exp.ref, owner=exp.owner, clock=exp.clock,
            due_at=_iso(exp.due_at), at_risk_at=_iso(exp.at_risk_at), detected_at=_iso(now),
        )

    async def _fetch_graph(self, cohort_def_id: str) -> Optional[Dict[str, Any]]:
        try:
            definition = await self._registry.get_cohort_definition(cohort_def_id)
        except Exception as exc:  # noqa: BLE001 — fail-soft: no snapshot → ADR-063 behaviour
            logger.warning("cohort sla: definition fetch failed for %s (runs without SLAs): %s",
                           cohort_def_id, exc)
            return None
        graph = (definition or {}).get("expectation_graph")
        return graph or None


# --------------------------------------------------------------------------- #
# snapshot accessors
# --------------------------------------------------------------------------- #
def _snapshot(cohort: Optional[CohortInstance]) -> Optional[Dict[str, Any]]:
    if cohort is None:
        return None
    return cohort.expectation_graph_snapshot or None


def _edges(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    return graph.get("edges") or []


def _node(graph: Dict[str, Any], node_id: str) -> Optional[Dict[str, Any]]:
    for n in graph.get("nodes") or []:
        if n.get("node_id") == node_id:
            return n
    return None


def _anchor_moment(edge: Dict[str, Any]) -> str:
    return str((edge.get("sla") or {}).get("anchor_moment", "completion"))


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None
