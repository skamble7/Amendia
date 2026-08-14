# tests/test_cohort_sla_runtime.py
"""ADR-064 P2 — cohort SLA runtime: snapshot-at-open, schedule, cancel-on-satisfy, void, fire-and-flag.

Deterministic: an injected clock drives BOTH scheduling anchors (open / arrival / completion == now()) and
firing (fire_due(now)). No sleeps. Drives the REAL CohortService (so the join/terminal/close wiring is
exercised) over mongomock repos + a fake registry that serves the definition's expectation_graph.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient

from amendia_contracts.process_pack import CohortMembership
from app.dal.cohort_repo import CohortInstanceRepository
from app.dal.cohort_sla_repo import CohortSlaExpectationRepository, CohortSlaTimerRepository
from app.db.mongo import (
    COHORT_INSTANCES, COHORT_SLA_EXPECTATIONS, COHORT_SLA_TIMERS, create_indexes,
)
from app.models.cohort_sla import SlaExpectationState as S
from app.services.business_clock import BusinessCalendar
from app.services.cohort_service import CohortService
from app.services.cohort_sla_service import CohortSlaService

DEF_ID = "ach_cohort"
KEY = "case_id"
MEMBERSHIP = CohortMembership(cohort_def_id=DEF_ID, correlation_key=KEY)
T0 = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def _utc(dt):
    """Normalize a datetime read back from mongomock (may be tz-naive) for comparison."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t = self.t + timedelta(**kw)


class FakePublisher:
    is_ready = True

    def __init__(self):
        self.events = []

    async def publish(self, event, routing_key, message_id):
        self.events.append((routing_key, event))


class FakeRegistry:
    def __init__(self, graph):
        self._graph = graph
        self.calls = 0

    async def get_cohort_definition(self, cohort_def_id):
        self.calls += 1
        return {"cohort_def_id": cohort_def_id, "expectation_graph": self._graph}


# --- graph fixtures (minimal per concern, so each test controls exactly one expectation) --------------

def _edge(frm, to, split="and", sla=None):
    e = {"from_node": frm, "to_node": to, "split": split}
    if sla is not None:
        e["sla"] = sla
    return e


def g_edge():
    """One a->b arrival edge (owner external, deadline 300, at-risk 180)."""
    return {
        "nodes": [{"node_id": "a", "node_type": "expected"}, {"node_id": "b", "node_type": "expected"}],
        "edges": [
            _edge("__start__", "a"),
            _edge("a", "b", sla={"anchor_moment": "completion", "satisfy_moment": "arrival",
                                 "deadline_seconds": 300, "at_risk_seconds": 180, "clock": "wall",
                                 "owner": "external"}),
            _edge("b", "__close__"),
        ],
    }


def g_node():
    """Node b's own runtime (arrival->completion) SLA (owner amendia, deadline 100, no at-risk)."""
    return {
        "nodes": [
            {"node_id": "a", "node_type": "expected"},
            {"node_id": "b", "node_type": "expected",
             "runtime_sla": {"deadline_seconds": 100, "at_risk_seconds": 0, "clock": "wall", "owner": "amendia"}},
        ],
        "edges": [_edge("__start__", "a"), _edge("a", "b"), _edge("b", "__close__")],
    }


def g_xor():
    """a XOR-splits to b/c; each branch is an arrival edge (deadline 500)."""
    xor = lambda: {"anchor_moment": "completion", "satisfy_moment": "arrival",  # noqa: E731
                   "deadline_seconds": 500, "at_risk_seconds": 0, "clock": "wall", "owner": "external"}
    return {
        "nodes": [
            {"node_id": "a", "node_type": "expected"},
            {"node_id": "b", "node_type": "conditional"},
            {"node_id": "c", "node_type": "conditional"},
        ],
        "edges": [
            _edge("__start__", "a"),
            _edge("a", "b", split="xor", sla=xor()),
            _edge("a", "c", split="xor", sla=xor()),
            _edge("b", "__close__"),
            _edge("c", "__close__"),
        ],
    }


def g_e2e():
    """End-to-end (open->close) SLA only (owner shared, deadline 500)."""
    return {
        "nodes": [{"node_id": "a", "node_type": "expected"}],
        "edges": [_edge("__start__", "a"), _edge("a", "__close__")],
        "end_to_end_sla": {"deadline_seconds": 500, "at_risk_seconds": 0, "clock": "wall", "owner": "shared"},
    }


def g_biz():
    """A business-clock arrival edge (deadline 3600s == 1 working hour)."""
    return {
        "nodes": [{"node_id": "a", "node_type": "expected"}, {"node_id": "b", "node_type": "expected"}],
        "edges": [
            _edge("__start__", "a"),
            _edge("a", "b", sla={"anchor_moment": "completion", "satisfy_moment": "arrival",
                                 "deadline_seconds": 3600, "at_risk_seconds": 0, "clock": "business",
                                 "owner": "external"}),
            _edge("b", "__close__"),
        ],
    }


# --- harness -----------------------------------------------------------------------------------------

class Harness(SimpleNamespace):
    async def arrive(self, value, node_id, pid=None):
        pid = pid or f"pi-{node_id}-{uuid.uuid4().hex[:6]}"
        m = SimpleNamespace(process_instance_id=pid, pack_key=node_id, pack_version="1.0.0",
                            correlation_id=pid, cohort_instance_id=None)
        cohort = await self.svc.join_on_spawn(m, MEMBERSHIP, {KEY: value})
        return cohort, pid

    async def complete(self, coh_id, node_id, pid):
        m = SimpleNamespace(process_instance_id=pid, pack_key=node_id, cohort_instance_id=coh_id)
        await self.svc.on_member_terminal(m)

    async def exp(self, coh_id, sla_id):
        return await self.exp_repo.get(coh_id, sla_id)

    def emitted(self, state):
        return [e for _, e in self.pub.events if e.get("state") == state]


@pytest_asyncio.fixture
async def make():
    async def _make(graph, *, calendar=None, clock=None):
        db = AsyncMongoMockClient()["amendia_test"]
        await create_indexes(db)
        cohort_repo = CohortInstanceRepository(db[COHORT_INSTANCES])
        exp_repo = CohortSlaExpectationRepository(db[COHORT_SLA_EXPECTATIONS])
        timer_repo = CohortSlaTimerRepository(db[COHORT_SLA_TIMERS])
        pub = FakePublisher()
        clock = clock or Clock()
        registry = FakeRegistry(graph)
        sla = CohortSlaService(exp_repo=exp_repo, timer_repo=timer_repo, cohort_repo=cohort_repo,
                               registry_client=registry, publisher=pub,
                               calendar=calendar or BusinessCalendar(), now=clock)
        svc = CohortService(repo=cohort_repo, publisher=pub, sla_service=sla)
        return Harness(db=db, cohort_repo=cohort_repo, exp_repo=exp_repo, timer_repo=timer_repo,
                       pub=pub, clock=clock, sla=sla, svc=svc, registry=registry)
    return _make


# --- backward-compat ---------------------------------------------------------------------------------

async def test_no_graph_is_pure_adr063(make):
    h = await make(None)                          # definition has no expectation_graph
    cohort, _ = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    assert await h.exp_repo.list_for_cohort(coh) == []          # no expectations
    assert await h.timer_repo.list_for_cohort(coh) == []        # no timers
    assert (await h.cohort_repo.get(coh)).expectation_graph_snapshot is None


# --- snapshot at open --------------------------------------------------------------------------------

async def test_snapshot_and_start_scheduling_on_open(make):
    h = await make(g_e2e())
    cohort, _ = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    snap = (await h.cohort_repo.get(coh)).expectation_graph_snapshot
    assert snap is not None and snap["end_to_end_sla"]["owner"] == "shared"   # forward-only snapshot
    assert h.registry.calls == 1                                              # fetched once, at open
    assert (await h.exp(coh, "e2e")).state == S.PENDING


async def test_snapshot_is_forward_only_ignores_later_definition_edits(make):
    h = await make(g_e2e())
    cohort, _ = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    # mutate the "definition" AFTER open — the in-flight cohort must keep what it opened under.
    h.registry._graph = g_edge()
    _, pb = await h.arrive("v", "a2", pid="pi-a2")   # a second member joins the SAME cohort (created=False)
    assert h.registry.calls == 1                     # NOT re-fetched; scheduling reads the snapshot
    assert (await h.cohort_repo.get(coh)).expectation_graph_snapshot["end_to_end_sla"]["owner"] == "shared"


# --- cancel-on-satisfy -------------------------------------------------------------------------------

async def test_arrival_satisfied_before_deadline_no_breach(make):
    h = await make(g_edge())
    cohort, pa = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    await h.complete(coh, "a", pa)                 # anchor T0 → a->b due T0+300
    assert (await h.exp(coh, "edge:a->b")).state == S.PENDING
    h.clock.advance(seconds=50)
    await h.arrive("v", "b")                       # arrives well before the deadline → satisfied
    assert (await h.exp(coh, "edge:a->b")).state == S.SATISFIED
    h.clock.advance(seconds=10_000)               # long past the (now cancelled) deadline
    assert await h.sla.fire_due() == 0
    assert h.emitted("breached") == []


# --- at-risk then breach, owner external -------------------------------------------------------------

async def test_arrival_never_arrives_at_risk_then_breach_external(make):
    h = await make(g_edge())
    cohort, pa = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    await h.complete(coh, "a", pa)                 # a->b: at_risk T0+180, due T0+300
    h.clock.advance(seconds=180)
    assert await h.sla.fire_due() == 1
    assert (await h.exp(coh, "edge:a->b")).state == S.AT_RISK
    assert len(h.emitted("at_risk")) == 1
    h.clock.advance(seconds=120)                  # T0+300
    assert await h.sla.fire_due() == 1
    e = await h.exp(coh, "edge:a->b")
    assert e.state == S.BREACHED and e.owner == "external"
    br = h.emitted("breached")[0]
    assert br["owner"] == "external" and br["kind"] == "edge" and br["due_at"] and br["detected_at"]


# --- runtime / completion SLA, owner amendia ---------------------------------------------------------

async def test_runtime_completion_sla_breaches_amendia(make):
    h = await make(g_node())
    cohort, pa = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    await h.complete(coh, "a", pa)
    _, pb = await h.arrive("v", "b")              # schedules node:b (arrival->completion, due T0+100)
    assert (await h.exp(coh, "node:b")).state == S.PENDING
    h.clock.advance(seconds=100)
    assert await h.sla.fire_due() == 1
    e = await h.exp(coh, "node:b")
    assert e.state == S.BREACHED and e.owner == "amendia" and e.kind.value == "node"


async def test_runtime_completion_satisfied_when_member_finishes_in_time(make):
    h = await make(g_node())
    cohort, pa = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    await h.complete(coh, "a", pa)
    _, pb = await h.arrive("v", "b")
    h.clock.advance(seconds=40)
    await h.complete(coh, "b", pb)                # completes before the 100s deadline
    assert (await h.exp(coh, "node:b")).state == S.SATISFIED
    h.clock.advance(seconds=1000)
    assert await h.sla.fire_due() == 0


# --- XOR sibling voiding -----------------------------------------------------------------------------

async def test_xor_sibling_arrival_voids_other_branch(make):
    h = await make(g_xor())
    cohort, pa = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    await h.complete(coh, "a", pa)                # schedules a->b and a->c (both pending)
    assert (await h.exp(coh, "edge:a->b")).state == S.PENDING
    assert (await h.exp(coh, "edge:a->c")).state == S.PENDING
    await h.arrive("v", "b")                      # b taken → satisfy a->b, void a->c
    assert (await h.exp(coh, "edge:a->b")).state == S.SATISFIED
    assert (await h.exp(coh, "edge:a->c")).state == S.VOIDED
    h.clock.advance(seconds=10_000)
    assert await h.sla.fire_due() == 0            # both resolved → nothing fires
    assert h.emitted("breached") == []


# --- close voids pending; end-to-end satisfied/breached ----------------------------------------------

async def test_close_voids_pending_and_satisfies_end_to_end(make):
    h = await make(g_e2e())
    cohort, pa = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    await h.complete(coh, "a", pa)
    await h.svc.close("v", "process_ended")       # CLOSE moment
    assert (await h.exp(coh, "e2e")).state == S.SATISFIED
    h.clock.advance(seconds=10_000)
    assert await h.sla.fire_due() == 0


async def test_close_voids_a_still_pending_arrival(make):
    h = await make(g_edge())
    cohort, pa = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    await h.complete(coh, "a", pa)                # a->b pending (b never arrives)
    await h.svc.close("v", "process_ended")       # close excuses the outstanding arrival
    assert (await h.exp(coh, "edge:a->b")).state == S.VOIDED
    h.clock.advance(seconds=10_000)
    assert await h.sla.fire_due() == 0 and h.emitted("breached") == []


async def test_end_to_end_breaches_when_close_never_comes(make):
    h = await make(g_e2e())
    cohort, _ = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    h.clock.advance(seconds=500)
    assert await h.sla.fire_due() == 1
    e = await h.exp(coh, "e2e")
    assert e.state == S.BREACHED and e.owner == "shared" and e.kind.value == "end_to_end"


# --- exactly-once + a breach that already fired stands -----------------------------------------------

async def test_satisfy_after_breach_leaves_breach_standing(make):
    h = await make(g_edge())
    cohort, pa = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    await h.complete(coh, "a", pa)
    h.clock.advance(seconds=300)
    assert await h.sla.fire_due() >= 1
    assert (await h.exp(coh, "edge:a->b")).state == S.BREACHED
    h.clock.advance(seconds=10)
    await h.arrive("v", "b")                      # arrives LATE, after the breach fired
    e = await h.exp(coh, "edge:a->b")
    assert e.state == S.BREACHED and e.arrived_late is True     # breach stands; truth recorded
    assert len(h.emitted("breached")) == 1                     # never a second breach


async def test_fire_racing_satisfy_yields_one_terminal_state(make):
    h = await make(g_edge())
    cohort, pa = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    await h.complete(coh, "a", pa)
    h.clock.advance(seconds=300)                  # deadline exactly reached
    # the poller fire and the arrival satisfy race on the same expectation.
    await asyncio.gather(h.sla.fire_due(), h.arrive("v", "b"))
    e = await h.exp(coh, "edge:a->b")
    assert e.state in (S.BREACHED, S.SATISFIED)                # exactly one terminal state
    assert len(h.emitted("breached")) <= 1                     # at most one breach event


# --- crash-safe: an overdue timer re-fires after downtime with detected_at > due_at ------------------

async def test_crash_safe_overdue_timer_fires_late(make):
    h = await make(g_edge())
    cohort, pa = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    await h.complete(coh, "a", pa)                # due T0+300
    # simulate downtime: the poller doesn't run until LONG after the deadline.
    h.clock.advance(seconds=5000)
    assert await h.sla.fire_due() >= 1
    e = await h.exp(coh, "edge:a->b")
    assert e.state == S.BREACHED
    assert _utc(e.detected_at) > _utc(e.due_at)               # honest: late-but-never-missed


# --- business clock end-to-end ------------------------------------------------------------------------

async def test_business_clock_schedules_across_non_working_window(make):
    # Anchor Fri 16:30; a 1-working-hour deadline lands Mon 09:30 (not Fri 17:30) — business, not wall.
    fri = datetime(2026, 8, 14, 16, 30, tzinfo=timezone.utc)
    h = await make(g_biz(), clock=Clock(fri))
    cohort, pa = await h.arrive("v", "a")
    coh = cohort.cohort_instance_id
    await h.complete(coh, "a", pa)               # a->b anchored Fri 16:30, business clock
    due = (await h.exp(coh, "edge:a->b")).due_at
    assert due.replace(tzinfo=timezone.utc) == datetime(2026, 8, 17, 9, 30, tzinfo=timezone.utc)
    # advancing wall-time to Fri 17:30 (1 real hour) must NOT breach — it's outside working hours.
    h.clock.advance(hours=1)
    assert await h.sla.fire_due() == 0
    assert (await h.exp(coh, "edge:a->b")).state == S.PENDING
