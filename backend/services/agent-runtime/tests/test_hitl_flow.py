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
from app.engine.executor import InProcessExecutor
from tests._stub_stack import stub_executor
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
        publisher=publisher, settings=settings, executor=stub_executor(), checkpointer=MemorySaver(),
    )
    # inject the bundle so no registry is needed
    engine._bundles[("wire-repair-standard", "1.0.0")] = PackBundle.from_seed_dir(settings.SEED_DIR)
    hitl = HitlDecisionService(hitl_repo=hitl_repo, instance_repo=instance_repo, engine=engine, publisher=publisher)
    return engine, hitl, instance_repo, hitl_repo, publisher


async def _start(engine, instance_repo, reason="AC01", exception_id="EXC-1", creditor="ACME LLC"):
    envelope = make_envelope(reason, exception_id=exception_id, creditor_name=creditor)
    inst = ProcessInstance.new(
        process_instance_id=f"pi-{exception_id}", trigger_id=exception_id,
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
    await hitl.claim(task.task_id, actor_id=user, actor_roles={task.role})
    dec = decision or ("complete" if task.hitl_mode.value == "manual" else "approve")
    await hitl.decide(task.task_id, actor_id=user, decision=dec)
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
    assert art.schema_ == "art.payment.assess_beneficiary_output@1.0.0"
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
        await hitl.claim(task.task_id, actor_id="analyst-1", actor_roles={task.role})
    assert ei.value.status_code == 403


async def test_decide_requires_claim_and_correct_user(env):
    engine, hitl, instance_repo, hitl_repo, _ = env
    inst = await _start(engine, instance_repo)
    task = await _open_task(hitl_repo, inst.process_instance_id)
    # decide before claim → 409
    with pytest.raises(HitlError) as ei:
        await hitl.decide(task.task_id, actor_id="analyst-1", decision="approve")
    assert ei.value.status_code == 409
    # claim by analyst-1, decide as someone else → 409
    await hitl.claim(task.task_id, actor_id="analyst-1", actor_roles={task.role})
    with pytest.raises(HitlError) as ei:
        await hitl.decide(task.task_id, actor_id="intruder", decision="approve")
    assert ei.value.status_code == 409


async def test_illegal_decision_rejected(env):
    engine, hitl, instance_repo, hitl_repo, _ = env
    inst = await _start(engine, instance_repo)
    task = await _open_task(hitl_repo, inst.process_instance_id)
    await hitl.claim(task.task_id, actor_id="analyst-1", actor_roles={task.role})
    with pytest.raises(HitlError) as ei:
        await hitl.decide(task.task_id, actor_id="analyst-1", decision="complete")  # not allowed for review_after
    assert ei.value.status_code == 400


async def test_edit_and_approve_revalidates(env):
    engine, hitl, instance_repo, hitl_repo, _ = env
    inst = await _start(engine, instance_repo)
    task = await _open_task(hitl_repo, inst.process_instance_id)
    await hitl.claim(task.task_id, actor_id="analyst-1", actor_roles={task.role})
    # invalid edit (missing required fields) → 400
    with pytest.raises(HitlError) as ei:
        await hitl.decide(task.task_id, actor_id="analyst-1", decision="edit_and_approve",
                          edits={"beneficiary": {"repair_verdict": "not-an-enum"}})
    assert ei.value.status_code == 400
    # valid edit → succeeds
    good = {"beneficiary": {"repair_verdict": "repairable", "confidence": 0.7, "rationale": "edited"}}
    await hitl.decide(task.task_id, actor_id="analyst-1", decision="edit_and_approve", edits=good)
    # the edited artifact is committed
    state = await engine.get_checkpoint_state(inst.process_instance_id, "wire-repair-standard", "1.0.0")
    assert state["artifacts"]["beneficiary"]["rationale"] == "edited"


async def test_reject_twice_fails_instance(env):
    engine, hitl, instance_repo, hitl_repo, _ = env
    inst = await _start(engine, instance_repo)
    pid = inst.process_instance_id
    # reject the first assess review → re-runs and re-presents a new task
    t1 = await _open_task(hitl_repo, pid)
    await hitl.claim(t1.task_id, actor_id="analyst-1", actor_roles={t1.role})
    await hitl.decide(t1.task_id, actor_id="analyst-1", decision="reject")
    t2 = await _open_task(hitl_repo, pid)
    assert t2 is not None and t2.task_id != t1.task_id
    await hitl.claim(t2.task_id, actor_id="analyst-1", actor_roles={t2.role})
    await hitl.decide(t2.task_id, actor_id="analyst-1", decision="reject")
    inst = await instance_repo.get(pid)
    assert inst.status is InstanceStatus.FAILED


async def _advance_to_obtaininfo(engine, hitl, instance_repo, hitl_repo, exception_id):
    """Drive a BE04 (needs-info) instance to the Task_ObtainInfo manual gate: approve the assess review
    (verdict needs_info) → the gateway routes to Task_ObtainInfo, a manual human task."""
    inst = await _start(engine, instance_repo, reason="BE04", exception_id=exception_id)
    pid = inst.process_instance_id
    await _approve_next(hitl, hitl_repo, pid)  # assess review_after → needs_info
    task = await _open_task(hitl_repo, pid)
    assert task is not None and task.element_id == "Task_ObtainInfo", task and task.element_id
    return pid, task


async def test_manual_gate_carries_readonly_inputs_and_editable_outputs(env):
    # Part 1: the manual gate surfaces the task's declared INPUT (dossier) as read-only context (no draft
    # marker) alongside the EDITABLE outputs (draft set) — and the markers survive materialization onto the
    # persisted task, so the frontend can render inputs read-only and outputs editable.
    engine, hitl, instance_repo, hitl_repo, _ = env
    _pid, task = await _advance_to_obtaininfo(engine, hitl, instance_repo, hitl_repo, "EXC-OBTAIN-1")
    assert task.hitl_mode.value == "manual"
    arts = {a.name: a for a in task.payload.artifacts}
    # read-only INPUT context — declared input (art.dining.order-style), resolved data present, NOT a draft
    assert "dossier" in arts, list(arts)
    assert not arts["dossier"].draft
    assert arts["dossier"].data, "the resolved read-only input data should be surfaced on the form"
    # editable OUTPUTS carry the draft marker; the human-authored one (no assist draft) is authored_by_human
    assert arts["rfi"].draft is True and not arts["rfi"].authored_by_human            # assist-drafted, editable
    assert arts["info_resolution"].draft is True and arts["info_resolution"].authored_by_human is True


async def test_manual_complete_missing_required_output_rejected_and_task_stays_open(env):
    # Part 2: an incomplete manual submit (missing the required human-authored output) is a RECOVERABLE 422 —
    # the task stays claimed/open and the instance does NOT fail. A valid resubmit then completes and resumes.
    engine, hitl, instance_repo, hitl_repo, _ = env
    pid, task = await _advance_to_obtaininfo(engine, hitl, instance_repo, hitl_repo, "EXC-OBTAIN-2")
    user = role_user(task.role)
    await hitl.claim(task.task_id, actor_id=user, actor_roles={task.role})
    # "approve the form with nothing authored" → the required human-authored info_resolution is missing → 422.
    # (The assist-drafted rfi is not required — it falls back to its draft — so it is not what trips this.)
    with pytest.raises(HitlError) as ei:
        await hitl.decide(task.task_id, actor_id=user, decision="complete", edits={})
    assert ei.value.status_code == 422
    assert "info_resolution" in ei.value.detail
    # the decision was NOT recorded: the task stays claimed (open), the instance did not fail
    again = await hitl_repo.get(task.task_id)
    assert again.status.value == "claimed" and again.decision is None
    inst = await instance_repo.get(pid)
    assert inst.status is not InstanceStatus.FAILED
    # a valid submit (the required human-authored output supplied) now completes and resumes
    await hitl.decide(task.task_id, actor_id=user, decision="complete",
                      edits={"info_resolution": {"outcome": "resolved", "details": "analyst note"}})
    done = await hitl_repo.get(task.task_id)
    assert done.status.value == "decided"


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
    # ADR-047 D2: MCP action caps have no propose-mode proposed_actions (the HITL gate + the tool's
    # post-hoc acknowledgement is the MCP reality); approving the gate lets the side-effect tool run.
    await hitl.claim(task.task_id, actor_id="approver-1", actor_roles={task.role})
    await hitl.decide(task.task_id, actor_id="approver-1", decision="approve")
    # flow proceeds to NotifyParties
    nxt = await _open_task(hitl_repo, pid)
    assert nxt.element_id == "Task_NotifyParties"
