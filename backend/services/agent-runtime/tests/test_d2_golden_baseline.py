# tests/test_d2_golden_baseline.py
"""ADR-047 D2 — Step 0: the GOLDEN REGRESSION NET (required before the re-home).

Captures a golden OUTCOME per wire seed pack per gateway branch — driven end-to-end through the *current*
skill-backed packs with the in-process engine (the same harness as the capstone test). The signature is the
observable contract the re-home must preserve: terminal ``status``/``outcome``, the produced-artifact set, and
the HITL task sequence. After D2.2/D2.3 re-home the seeds onto MCP, these MUST reproduce byte-identical — that
equivalence, not merely "tests green", is the acceptance bar (ADR-047 D2 §Regression safety).

Baseline capture: the committed ``golden/d2_seed_outcomes.json`` is the source of truth. Regenerate it
deliberately (only when a *known* behavior change is intended) with ``D2_GOLDEN_WRITE=1``; otherwise the test
asserts every pack×branch still matches it.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest_asyncio
import pytest
from langgraph.checkpoint.memory import MemorySaver
from mongomock_motor import AsyncMongoMockClient

from app.dal.hitl_task_repo import HitlTaskRepository
from app.dal.instance_repo import ProcessInstanceRepository
from app.dal.timer_repo import TimerRepository
from app.db.mongo import HITL_TASKS, PROCESS_INSTANCES, TIMERS, create_indexes
from app.engine.bundle import PackBundle
from app.engine.compiler import compile_graph
from app.engine.engine import ProcessEngine
from app.engine.executor import InProcessExecutor
from app.models.process_instance import InstanceStatus, ProcessInstance
from app.services.timer_service import TimerService
from amendia_contracts.hitl_task import TaskStatus
from tests._wire import make_envelope, role_user

_SEED_ROOT = Path(__file__).resolve().parents[1] / "seed"
_GOLDEN = Path(__file__).parent / "golden" / "d2_seed_outcomes.json"
_T0 = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)

# The wire seed packs D2 re-homes, and a representative envelope per gateway branch. The signature captured is
# whatever the CURRENT skill-backed pack does — the re-home must reproduce it. (creditor "SANCTIONED …" trips
# the sanctions-hit path; reason codes drive the repair/needs-info branches — see the assess/sanctions sims.)
_PACKS = ["wire-repair-standard", "wire-repair-agentic", "wire-repair-dmn", "wire-repair-screening"]
_BRANCHES = {
    "repairable_ac01": dict(reason_code="AC01"),
    "repairable_rc01": dict(reason_code="RC01"),
    "needs_info_be04": dict(reason_code="BE04"),
    "screening_hit": dict(reason_code="AC01", creditor_name="SANCTIONED PARTY LLC"),
}


class _Clock:
    def __init__(self):
        self.t = _T0

    def __call__(self):
        return self.t


class _FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, doc, rk, mid):
        self.events.append((rk, doc))


class _Settings:
    EXECUTION_PROFILE = "common_executable"
    SIMULATION_MODE = True
    SELF_BASE_URL = "http://rt"


async def _signature(seed_dir: Path, envelope: dict, *, executor=None, max_steps: int = 40) -> dict:
    """Run one envelope through one seed pack to a terminal (or waiting) state; return its golden signature.

    ``executor`` defaults to the native ``InProcessExecutor`` (skill/sim path). Pass an executor with an
    injected MCP client to run an MCP-backed (re-homed) pack — the equivalence check for ADR-047 D2."""
    try:
        bundle = PackBundle.from_seed_dir(seed_dir)
    except Exception as exc:  # noqa: BLE001 — a load/parse failure is itself part of the signature
        return {"status": f"LOAD_ERROR: {type(exc).__name__}: {exc}"}

    pk, pv = bundle.manifest.pack_key, bundle.manifest.version
    db = AsyncMongoMockClient()["amendia_golden"]
    await create_indexes(db)
    instances = ProcessInstanceRepository(db[PROCESS_INSTANCES])
    hitl = HitlTaskRepository(db[HITL_TASKS])
    timers = TimerService(TimerRepository(db[TIMERS]), now=_Clock())
    cp = MemorySaver()
    eng = ProcessEngine(registry=None, instance_repo=instances, hitl_repo=hitl, publisher=_FakePublisher(),
                        settings=_Settings(), executor=executor or InProcessExecutor(), checkpointer=cp,
                        timer_service=timers)
    eng._bundles[(pk, pv)] = bundle
    eng._graphs[(pk, pv)] = compile_graph(bundle, eng._executor, simulation=True, checkpointer=cp,
                                          profile="common_executable")

    pid = f"pi-{pk}"
    inst = ProcessInstance.new(process_instance_id=pid, exception_id="EXC-golden", pack_key=pk, pack_version=pv)
    await instances.insert(inst)
    hitl_seq: list = []
    visits: dict = {}
    looped = False
    try:
        await eng.start(inst, envelope)
        for _ in range(max_steps):
            cur = await instances.get(pid)
            if cur.status in (InstanceStatus.COMPLETED, InstanceStatus.FAILED):
                break
            open_tasks = await hitl.list(process_instance_id=pid, status="open")
            if not open_tasks:
                break  # waiting on a timer/message with no human gate — a stable terminal-ish signature
            t = open_tasks[0]
            # An auto-approve policy can't terminate a needs-info re-assessment loop (the stateless sim keeps
            # returning the same verdict). Detect the cycle and record a COMPACT, stable signature.
            visits[t.element_id] = visits.get(t.element_id, 0) + 1
            if visits[t.element_id] >= 3:
                looped = True
                break
            mode = t.hitl_mode.value
            hitl_seq.append([t.element_id, mode])
            dec = {"decision": "complete" if mode == "manual" else "approve", "decided_by": role_user(t.role)}
            await hitl.transition_status(t.task_id, expected_status=TaskStatus.OPEN, new_status=TaskStatus.DECIDED,
                                         set_fields={"decision": {**dec, "decided_at": _T0.isoformat()}})
            await eng.resume(pid, dec, interrupt_id=t.interrupt_id)
    except Exception as exc:  # noqa: BLE001 — a runtime failure is part of the signature
        return {"status": f"RUN_ERROR: {type(exc).__name__}: {exc}", "hitl": hitl_seq}

    final = await instances.get(pid)
    try:
        state = eng._graphs[(pk, pv)].get_state({"configurable": {"thread_id": pid}}).values
        artifacts = sorted((state.get("artifacts") or {}).keys())
    except Exception:  # noqa: BLE001
        artifacts = []
    sig = {"status": ("waiting_hitl_loop" if looped else final.status.value),
           "outcome": final.outcome, "artifacts": artifacts, "hitl": hitl_seq}
    # for a failed run, record WHY (stable, truncated) — e.g. the nemoclaw-only deep_agent fail-close.
    if final.status is InstanceStatus.FAILED and getattr(final, "last_error", None):
        sig["error"] = str(final.last_error)[:120]
    return sig


async def _compute_all() -> dict:
    # ADR-047 D2: the seed packs are now MCP-backed — run them on the SIM_CAPABILITIES-free stub stack.
    from tests._stub_stack import stub_executor
    out: dict = {}
    for pack in _PACKS:
        seed_dir = _SEED_ROOT / pack
        out[pack] = {}
        for branch, kw in _BRANCHES.items():
            out[pack][branch] = await _signature(seed_dir, make_envelope(**kw), executor=stub_executor())
    return out


@pytest.mark.asyncio
async def test_seed_packs_match_golden_outcomes():
    computed = await _compute_all()

    if os.environ.get("D2_GOLDEN_WRITE") or not _GOLDEN.exists():
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(computed, indent=2, sort_keys=True) + "\n")
        pytest.skip(f"golden baseline written to {_GOLDEN} ({sum(len(v) for v in computed.values())} signatures)")

    golden = json.loads(_GOLDEN.read_text())
    mismatches = []
    for pack, branches in golden.items():
        for branch, sig in branches.items():
            got = computed.get(pack, {}).get(branch)
            if got != sig:
                mismatches.append(f"{pack}/{branch}: golden={sig} got={got}")
    assert not mismatches, "D2 re-home changed seed behavior:\n" + "\n".join(mismatches)


def test_golden_baseline_is_committed():
    # once captured, the baseline must be a committed artifact (the regression net), not regenerated silently.
    assert _GOLDEN.exists(), "run the golden test once (writes the baseline), then commit golden/d2_seed_outcomes.json"
    data = json.loads(_GOLDEN.read_text())
    assert set(data) == set(_PACKS) and all(set(v) == set(_BRANCHES) for v in data.values())
