# tests/test_cohort_repo.py
"""ADR-063 Phase 1 — cohort repo: atomic get-or-create + idempotent member ops."""
from __future__ import annotations

import asyncio

import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient

from app.dal.cohort_repo import CohortInstanceRepository
from app.db.mongo import COHORT_INSTANCES, create_indexes
from app.models.cohort_instance import CohortState


@pytest_asyncio.fixture
async def repo():
    db = AsyncMongoMockClient()["amendia_test"]
    await create_indexes(db)
    return CohortInstanceRepository(db[COHORT_INSTANCES])


async def test_get_or_open_creates_then_reuses(repo):
    cohort, created = await repo.get_or_open("1v23p", "wire_transfer_cohort")
    assert created is True
    assert cohort.state == CohortState.OPEN
    assert cohort.correlation_value == "1v23p"
    assert cohort.cohort_def_id == "wire_transfer_cohort"

    same, created2 = await repo.get_or_open("1v23p", "wire_transfer_cohort")
    assert created2 is False
    assert same.cohort_instance_id == cohort.cohort_instance_id  # dedup by correlation_value


async def test_get_or_open_is_atomic_under_concurrency(repo):
    # Two concurrent opens for the same value must collapse to ONE row (unique index + first-writer-wins).
    results = await asyncio.gather(*[repo.get_or_open("same-val", "wire_transfer_cohort") for _ in range(8)])
    ids = {c.cohort_instance_id for c, _ in results}
    assert len(ids) == 1                                   # exactly one cohort instance
    assert sum(1 for _, created in results if created) == 1  # exactly one creator


async def test_add_member_is_idempotent(repo):
    cohort, _ = await repo.get_or_open("v", "c")
    cid = cohort.cohort_instance_id

    assert await repo.add_member(cid, "pi-1", "pack-a") is True
    assert await repo.add_member(cid, "pi-2", "pack-b") is True
    assert await repo.add_member(cid, "pi-1", "pack-a") is False  # re-add → no-op

    fresh = await repo.get(cid)
    assert [m.process_instance_id for m in fresh.members] == ["pi-1", "pi-2"]  # no duplicate
    assert fresh.active_member_count == 2                                       # count didn't double


async def test_mark_member_terminal_decrements_once(repo):
    cohort, _ = await repo.get_or_open("v", "c")
    cid = cohort.cohort_instance_id
    await repo.add_member(cid, "pi-1", "pack-a")
    await repo.add_member(cid, "pi-2", "pack-b")

    after = await repo.mark_member_terminal(cid, "pi-1")
    assert after.active_member_count == 1
    assert next(m for m in after.members if m.process_instance_id == "pi-1").terminal is True

    # idempotent: re-draining an already-terminal member changes nothing
    assert await repo.mark_member_terminal(cid, "pi-1") is None
    assert (await repo.get(cid)).active_member_count == 1
