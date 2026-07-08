# tests/test_hitl_flow.py
"""Part E: HITL task materialization, claim/decide guards, SoD, resume — driven
through the real ProcessEngine + HitlDecisionService with an in-memory saver."""
from __future__ import annotations

import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import MemorySaver

from app.config import settings
from app.dal.hitl_task_repo import HitlTaskRepository
from app.dal.instance_repo import ProcessInstanceRepository
from app.db.mongo import HITL_TASKS, PROCESS_INSTANCES, create_indexes
from app.engine.bundle import PackBundle
from app.engine.engine import ProcessEngine
from app.engine.executor import Executor
from app.models.process_instance import InstanceStatus, ProcessInstance
from app.services.hitl_service import HitlDecisionService, HitlError
from tests._wire import make_envelope, role_user


class FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, event, routing_key, message_id):
        self.events.append((routing_key, event))


@pytest_asyncio.fixture
async def env():
    from mongomock_motor import AsyncMongoMockClient
    db = AsyncMongoMockClient()["amendia_test"]
    await create_indexes(db)
    instance_repo = ProcessInstanceRepository(db[PROCESS_INSTANCES])
    hitl_repo = HitlTaskRepository(db[HITL_TASKS])
    publisher = FakePublisher()
    engine = ProcessEngine(
        registry=None, instance_repo=instance_repo, hitl_repo=hitl_repo,
        publisher=publisher, settings=settings, executor=Executor(), checkpointer=MemorySaver(),
    )
    # inject the bundle so no registry is needed
    engine._bundles[("wire-repair-standard", "1.0.0")] = PackBundle.from_seed_dir(settings.SEED_DIR)
    hitl = HitlDecisionService(hitl_repo=hitl_repo, instance_repo=instance_repo, engine=engine, publisher=publisher)
    return engine, hitl, instance_repo, hitl_repo, publisher


async def _start(engine, instance_repo, reason="AC01", exception_id="EXC-1", creditor="ACME LLC"):
    envelope = make_envelope(reason, exception_id=exception_id, creditor_name=creditor)
    inst = ProcessInstance.new(
        process_instance_id=f"pi-{exception_id}", tenant="bank-alpha", exception_id=exception_id,
        pack_key="wire-repair-standard", pack_version="1.0.0", correlation_id=exception_id,
    )
    await instance_repo.insert(inst)
    await engine.start(inst, envelope)
    return inst


async def _open_task(hitl_repo, pid):
    tasks = await hitl_repo.list(status="open", process_instance_id=pid)
    return tasks[0] if tasks else None


async def _approve_next(hitl, hitl_repo, pid, *, decision=None):
    task = await _open_task(hitl_repo, pid)
    assert task is not None, "expected an open task"
    user = role_user(task.role)
    await hitl.claim(task.task_id, user_id=user, role=task.role)
    dec = decision or ("complete" if task.hitl_mode.value == "manual" else "approve")
    await hitl.decide(task.task_id, user_id=user, decision=dec)
    return task


async def test_first_gate_is_assess_review_with_pinned_schema(env):
    engine, hitl, instance_repo, hitl_repo, _ = env
    inst = await _start(engine, instance_repo)
    task = await _open_task(hitl_repo, inst.process_instance_id)
    assert task.element_id == "Task_AssessRepairability"
    assert task.hitl_mode.value == "review_after"
    assert [d.value for d in task.allowed_decisions] == ["approve", "edit_and_approve", "reject"]
    # payload artifact carries a pinned schema ref
    art = task.payload.artifacts[0]
    assert art.schema_ == "art.payment.repair_verdict@1.0.0"
    assert art.data["repair_verdict"] == "repairable"


async def test_full_ac01_completes_with_all_modes_and_sod(env):
    engine, hitl, instance_repo, hitl_repo, publisher = env
    inst = await _start(engine, instance_repo)
    pid = inst.process_instance_id

    seen_modes = []
    seen_sod = {}
    for _ in range(10):
        task = await _open_task(hitl_repo, pid)
        if task is None:
            break
        seen_modes.append(task.hitl_mode.value)
        seen_sod[task.element_id] = list(task.sod.excluded_users or [])
        await _approve_next(hitl, hitl_repo, pid)

    inst = await instance_repo.get(pid)
    assert inst.status is InstanceStatus.COMPLETED
    assert inst.outcome == "End_Resolved"
    assert set(inst.artifact_names) >= {"dossier", "beneficiary", "repair", "screening", "resolution"}
    # all four modes exercised
    assert set(seen_modes) == {"review_after", "manual", "approve_result", "approve_actions"}
    # SoD: the analyst who reviewed DraftRepair is excluded from ApproveRepair
    assert "analyst-1" in seen_sod["Task_ApproveRepair"]
    # a completed event was published
    assert any("process_completed" in rk for rk, _ in publisher.events)


async def test_sod_blocks_excluded_user_at_claim(env):
    engine, hitl, instance_repo, hitl_repo, _ = env
    inst = await _start(engine, instance_repo)
    pid = inst.process_instance_id
    # advance to the ApproveRepair manual gate
    await _approve_next(hitl, hitl_repo, pid)  # Assess (analyst-1)
    await _approve_next(hitl, hitl_repo, pid)  # DraftRepair (analyst-1)
    task = await _open_task(hitl_repo, pid)
    assert task.element_id == "Task_ApproveRepair"
    assert "analyst-1" in (task.sod.excluded_users or [])
    with pytest.raises(HitlError) as ei:
        await hitl.claim(task.task_id, user_id="analyst-1", role=task.role)
    assert ei.value.status_code == 403


async def test_decide_requires_claim_and_correct_user(env):
    engine, hitl, instance_repo, hitl_repo, _ = env
    inst = await _start(engine, instance_repo)
    task = await _open_task(hitl_repo, inst.process_instance_id)
    # decide before claim → 409
    with pytest.raises(HitlError) as ei:
        await hitl.decide(task.task_id, user_id="analyst-1", decision="approve")
    assert ei.value.status_code == 409
    # claim by analyst-1, decide as someone else → 409
    await hitl.claim(task.task_id, user_id="analyst-1", role=task.role)
    with pytest.raises(HitlError) as ei:
        await hitl.decide(task.task_id, user_id="intruder", decision="approve")
    assert ei.value.status_code == 409


async def test_illegal_decision_rejected(env):
    engine, hitl, instance_repo, hitl_repo, _ = env
    inst = await _start(engine, instance_repo)
    task = await _open_task(hitl_repo, inst.process_instance_id)
    await hitl.claim(task.task_id, user_id="analyst-1", role=task.role)
    with pytest.raises(HitlError) as ei:
        await hitl.decide(task.task_id, user_id="analyst-1", decision="complete")  # not allowed for review_after
    assert ei.value.status_code == 400


async def test_edit_and_approve_revalidates(env):
    engine, hitl, instance_repo, hitl_repo, _ = env
    inst = await _start(engine, instance_repo)
    task = await _open_task(hitl_repo, inst.process_instance_id)
    await hitl.claim(task.task_id, user_id="analyst-1", role=task.role)
    # invalid edit (missing required fields) → 400
    with pytest.raises(HitlError) as ei:
        await hitl.decide(task.task_id, user_id="analyst-1", decision="edit_and_approve",
                          edits={"beneficiary": {"repair_verdict": "not-an-enum"}})
    assert ei.value.status_code == 400
    # valid edit → succeeds
    good = {"beneficiary": {"repair_verdict": "repairable", "confidence": 0.7, "rationale": "edited"}}
    await hitl.decide(task.task_id, user_id="analyst-1", decision="edit_and_approve", edits=good)
    # the edited artifact is committed
    state = await engine.get_checkpoint_state(inst.process_instance_id, "wire-repair-standard", "1.0.0")
    assert state["artifacts"]["beneficiary"]["rationale"] == "edited"


async def test_reject_twice_fails_instance(env):
    engine, hitl, instance_repo, hitl_repo, _ = env
    inst = await _start(engine, instance_repo)
    pid = inst.process_instance_id
    # reject the first assess review → re-runs and re-presents a new task
    t1 = await _open_task(hitl_repo, pid)
    await hitl.claim(t1.task_id, user_id="analyst-1", role=t1.role)
    await hitl.decide(t1.task_id, user_id="analyst-1", decision="reject")
    t2 = await _open_task(hitl_repo, pid)
    assert t2 is not None and t2.task_id != t1.task_id
    await hitl.claim(t2.task_id, user_id="analyst-1", role=t2.role)
    await hitl.decide(t2.task_id, user_id="analyst-1", decision="reject")
    inst = await instance_repo.get(pid)
    assert inst.status is InstanceStatus.FAILED


async def test_approve_actions_partial_approval_threads_ids(env):
    engine, hitl, instance_repo, hitl_repo, _ = env
    inst = await _start(engine, instance_repo)
    pid = inst.process_instance_id
    # advance to the ApplyRepair approve_actions gate
    for _ in range(4):  # Assess, DraftRepair, ApproveRepair, SanctionsRescreen
        await _approve_next(hitl, hitl_repo, pid)
    task = await _open_task(hitl_repo, pid)
    assert task.element_id == "Task_ApplyRepair"
    assert task.hitl_mode.value == "approve_actions"
    assert task.payload.proposed_actions  # proposed actions present
    # partial approval with an explicit action id list
    await hitl.claim(task.task_id, user_id="approver-1", role=task.role)
    await hitl.decide(task.task_id, user_id="approver-1", decision="approve",
                      approved_action_ids=["act-apply-repair"])
    # flow proceeds to NotifyParties
    nxt = await _open_task(hitl_repo, pid)
    assert nxt.element_id == "Task_NotifyParties"
