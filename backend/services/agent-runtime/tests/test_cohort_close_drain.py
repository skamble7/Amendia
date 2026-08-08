# tests/test_cohort_close_drain.py
"""ADR-063 Phase 2 — the close state machine + drain: open → closing → closed, and the close/last-member race.

The finalize (`closing → closed`) is a single atomic ``{state: CLOSING, active_member_count: 0}`` conditional
that both the close path and the last member-terminal drain run — so exactly one caller wins → exactly one
``closed`` event, whatever the interleaving.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient

from amendia_contracts.process_pack import CohortMembership
from app.dal.cohort_repo import CohortInstanceRepository
from app.db.mongo import COHORT_INSTANCES, create_indexes
from app.models.cohort_instance import CohortState
from app.services.cohort_service import CohortService

MEMBERSHIP = CohortMembership(cohort_def_id="wire_transfer_cohort", correlation_key="exception_id")


class FakePublisher:
    is_ready = True

    def __init__(self):
        self.events = []

    async def publish(self, event, routing_key, message_id):
        self.events.append(event)


@pytest_asyncio.fixture
async def svc():
    db = AsyncMongoMockClient()["amendia_test"]
    await create_indexes(db)
    repo = CohortInstanceRepository(db[COHORT_INSTANCES])
    pub = FakePublisher()
    return SimpleNamespace(repo=repo, pub=pub, service=CohortService(repo=repo, publisher=pub))


def _member(pid, coh_id):
    return SimpleNamespace(process_instance_id=pid, pack_key="wire-repair-standard",
                           pack_version="1.0.0", correlation_id=pid, cohort_instance_id=coh_id)


def _ops(pub, op):
    return [e for e in pub.events if e.get("op") == op]


async def _open_with_members(repo, value, n):
    cohort, _ = await repo.get_or_open(value, "wire_transfer_cohort")
    for i in range(n):
        await repo.add_member(cohort.cohort_instance_id, f"pi-{i}", "wire-repair-standard")
    return cohort.cohort_instance_id


async def test_close_with_no_active_members_goes_straight_to_closed(svc):
    coh_id = await _open_with_members(svc.repo, "v0", 2)
    for i in range(2):                                        # both members already terminal → active 0
        await svc.repo.mark_member_terminal(coh_id, f"pi-{i}")

    await svc.service.close("v0", "process_ended")
    assert (await svc.repo.get(coh_id)).state == CohortState.CLOSED
    assert len(_ops(svc.pub, "closed")) == 1
    assert _ops(svc.pub, "closing") == []                    # no member in flight → never CLOSING-then-CLOSED


async def test_close_with_active_members_waits_then_drains_to_closed(svc):
    coh_id = await _open_with_members(svc.repo, "v1", 2)

    await svc.service.close("v1", "process_ended")           # members still running → closing
    assert (await svc.repo.get(coh_id)).state == CohortState.CLOSING
    assert len(_ops(svc.pub, "closing")) == 1
    assert _ops(svc.pub, "closed") == []

    await svc.service.on_member_terminal(_member("pi-0", coh_id))   # first drains, still one active
    assert (await svc.repo.get(coh_id)).state == CohortState.CLOSING
    assert _ops(svc.pub, "closed") == []

    await svc.service.on_member_terminal(_member("pi-1", coh_id))   # last drains → finalize → closed
    assert (await svc.repo.get(coh_id)).state == CohortState.CLOSED
    assert len(_ops(svc.pub, "closed")) == 1


async def test_close_racing_last_member_yields_exactly_one_closed(svc):
    coh_id = await _open_with_members(svc.repo, "v2", 1)      # a single in-flight member

    # close and the last member's terminal fire concurrently.
    await asyncio.gather(
        svc.service.close("v2", "process_ended"),
        svc.service.on_member_terminal(_member("pi-0", coh_id)),
    )
    final = await svc.repo.get(coh_id)
    assert final.state == CohortState.CLOSED
    assert final.active_member_count == 0
    assert len(_ops(svc.pub, "closed")) == 1                 # exactly one closed, whatever the interleaving
    assert len(_ops(svc.pub, "closing")) <= 1                # a closing may or may not precede it


async def test_close_finalize_losing_to_drain_emits_no_trailing_closing(svc):
    # The stray-`closing` bug: force the exact interleave where the last member finalizes to CLOSED inside
    # close()'s begin_close→finalize gap. close()'s own finalize then matches nothing — it must stay SILENT
    # (the drain already emitted the single `closed`), never emit a trailing `closing` after `closed`.
    coh_id = await _open_with_members(svc.repo, "vrace", 1)   # one in-flight member

    real_finalize = svc.repo.finalize_if_drained
    fired = {"once": False}

    async def racing_finalize(cid):
        # On close()'s FIRST finalize attempt, deterministically run the last member's drain to completion
        # (which wins finalize → CLOSED, emits `closed`) BEFORE delegating to the real finalize.
        if not fired["once"]:
            fired["once"] = True
            await svc.service.on_member_terminal(_member("pi-0", coh_id))
        return await real_finalize(cid)

    svc.repo.finalize_if_drained = racing_finalize
    await svc.service.close("vrace", "process_ended")

    ops = [e["op"] for e in svc.pub.events]
    assert ops.count("closed") == 1                          # exactly one closed (drain's)
    assert "closing" not in ops                              # close() lost the finalize → stayed silent
    # and defensively: no `closing` anywhere AFTER the `closed`
    assert not any(op == "closing" for op in ops[ops.index("closed") + 1:])
    assert (await svc.repo.get(coh_id)).state == CohortState.CLOSED


async def test_duplicate_close_is_idempotent(svc):
    coh_id = await _open_with_members(svc.repo, "v3", 0)      # no members → first close goes to closed
    await svc.service.close("v3", "done")
    await svc.service.close("v3", "done")                     # duplicate on a closed cohort
    assert len(_ops(svc.pub, "closed")) == 1                  # not re-emitted
    assert (await svc.repo.get(coh_id)).state == CohortState.CLOSED


async def test_close_with_no_cohort_is_noop(svc):
    await svc.service.close("does-not-exist", "done")         # benign — no crash, no event
    assert svc.pub.events == []


async def test_join_to_closed_is_late_join_but_closing_is_normal(svc):
    # closed cohort → a late sibling is flagged late_join
    coh_closed = await _open_with_members(svc.repo, "vc", 0)
    await svc.service.close("vc", "done")                     # → closed
    svc.pub.events.clear()
    joined = await svc.service.join_on_spawn(_member("pi-late", coh_closed), MEMBERSHIP,
                                             {"exception_id": "vc"})
    assert joined is not None and len(_ops(svc.pub, "late_join")) == 1
    assert _ops(svc.pub, "member_joined") == []

    # closing (not yet closed) cohort → a new segment joins NORMALLY and keeps it alive
    coh_closing = await _open_with_members(svc.repo, "vk", 1)
    await svc.service.close("vk", "done")                    # still one active → closing
    svc.pub.events.clear()
    await svc.service.join_on_spawn(_member("pi-new", coh_closing), MEMBERSHIP, {"exception_id": "vk"})
    assert len(_ops(svc.pub, "member_joined")) == 1          # normal join, NOT an anomaly
    assert _ops(svc.pub, "late_join") == []
    assert (await svc.repo.get(coh_closing)).active_member_count == 2  # kept alive
