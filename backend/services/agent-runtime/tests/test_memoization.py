# tests/test_memoization.py
"""ADR-019 Part A — per-instance capability memoization (fixes ADR-016 trap 2 / ADR-017 trap 5).

Drives the compiled wire-repair graph with a counting executor so we can assert exactly how
many times a capability is invoked across HITL interrupt/resume. The four correctness cases:
  1. approve on review_after → the *originally produced* artifact commits; model NOT re-invoked.
  2. edit_and_approve → the human's edit wins; memo does not clobber it.
  3. reject → re-run → the capability genuinely re-runs; the reviewed (2nd) artifact commits.
  4. no cross-instance leakage; native byte-identical with the flag off.
"""
from __future__ import annotations

from typing import Any, Dict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.compiler import compile_graph
from app.engine.executor import InProcessExecutor
from app.engine.executor.base import ExecutionContext
from app.engine.executor.memo import InMemoryMemoStore, inputs_hash
from app.engine.state import initial_state
from tests._wire import default_decision, make_envelope, role_user


class CountingExecutor:
    """Wraps InProcessExecutor, counting real (uncached) capability invocations per element."""

    def __init__(self, memo=None, memoize=False) -> None:
        self._inner = InProcessExecutor()
        self._memo = memo
        self._memoize = memoize and memo is not None
        self.calls: Dict[str, int] = {}

    def execute(self, descriptor, inputs, ctx: ExecutionContext) -> Dict[str, Any]:
        from app.engine.executor.memo import memoized_execute

        def run():
            eid = (ctx.extras or {}).get("element_id", descriptor.capability_id)
            self.calls[eid] = self.calls.get(eid, 0) + 1
            return self._inner.execute(descriptor, inputs, ctx)

        return memoized_execute(memo=self._memo, enabled=self._memoize, inputs=inputs, ctx=ctx, run=run)


def _bundle() -> PackBundle:
    return PackBundle.from_seed_dir(settings.SEED_DIR)


def _graph(executor):
    return compile_graph(_bundle(), executor, simulation=True, checkpointer=MemorySaver())


def _initial(reason="AC01", exception_id="EXC-MEMO"):
    return initial_state(
        envelope=make_envelope(reason, exception_id=exception_id),
        trace={"correlation_id": exception_id},
        pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"},
    )


def _run_to_gate(app, cfg, initial):
    r = app.invoke(initial, cfg)
    return r


def _first_gate_of(app, cfg, initial, element_id):
    """Drive until the gate for element_id, approving everything before it. Returns payload."""
    r = app.invoke(initial, cfg)
    while "__interrupt__" in r:
        p = r["__interrupt__"][0].value
        if p["element_id"] == element_id:
            return p, r
        r = app.invoke(Command(resume=default_decision(p)), cfg)
    raise AssertionError(f"never reached gate {element_id}")


# --------------------------------------------------------------------------- #
def test_approve_review_after_does_not_reinvoke_and_commits_reviewed_artifact():
    memo = InMemoryMemoStore()
    ex = CountingExecutor(memo=memo, memoize=True)
    app = _graph(ex)
    cfg = {"configurable": {"thread_id": "pi-approve"}}

    # Task_DraftRepair is review_after (an llm capability). Reach its gate.
    payload, r = _first_gate_of(app, cfg, _initial(), "Task_DraftRepair")
    reviewed = payload["artifacts"][0]["data"]
    calls_at_gate = ex.calls["Task_DraftRepair"]
    assert calls_at_gate == 1  # produced once before the gate

    # Approve → resume replays the node; memo must serve the artifact, NOT re-invoke.
    r = app.invoke(Command(resume={"decision": "approve", "decided_by": role_user(payload.get("role"))}), cfg)
    # drive the rest to completion
    while "__interrupt__" in r:
        p = r["__interrupt__"][0].value
        r = app.invoke(Command(resume=default_decision(p)), cfg)

    assert ex.calls["Task_DraftRepair"] == 1, "capability was re-invoked on resume (trap 2 not fixed)"
    assert r["artifacts"]["repair"] == reviewed, "committed artifact differs from the reviewed one"


def test_edit_and_approve_commits_human_edit_not_memo():
    memo = InMemoryMemoStore()
    ex = CountingExecutor(memo=memo, memoize=True)
    app = _graph(ex)
    cfg = {"configurable": {"thread_id": "pi-edit"}}

    payload, r = _first_gate_of(app, cfg, _initial(), "Task_DraftRepair")
    original = payload["artifacts"][0]["data"]
    edited = dict(original)
    edited["justification"] = "HUMAN EDITED justification"

    r = app.invoke(Command(resume={
        "decision": "edit_and_approve",
        "decided_by": role_user(payload.get("role")),
        "edits": {"repair": edited},
    }), cfg)
    while "__interrupt__" in r:
        p = r["__interrupt__"][0].value
        r = app.invoke(Command(resume=default_decision(p)), cfg)

    assert r["artifacts"]["repair"]["justification"] == "HUMAN EDITED justification"
    assert ex.calls["Task_DraftRepair"] == 1  # not re-invoked; edit applied via decision path


def test_reject_then_rerun_genuinely_reinvokes_capability():
    memo = InMemoryMemoStore()
    ex = CountingExecutor(memo=memo, memoize=True)
    app = _graph(ex)
    cfg = {"configurable": {"thread_id": "pi-reject"}}

    payload, r = _first_gate_of(app, cfg, _initial(), "Task_DraftRepair")
    assert ex.calls["Task_DraftRepair"] == 1

    # Reject once → the node must genuinely re-run the capability (fresh memo attempt).
    r = app.invoke(Command(resume={"decision": "reject", "decided_by": role_user(payload.get("role"))}), cfg)
    assert ex.calls["Task_DraftRepair"] == 2, "reject did not re-invoke the capability"

    # Now approve the re-produced artifact and finish; approve replay must not re-invoke again.
    while "__interrupt__" in r:
        p = r["__interrupt__"][0].value
        if p["element_id"] == "Task_DraftRepair":
            r = app.invoke(Command(resume={"decision": "approve", "decided_by": role_user(p.get("role"))}), cfg)
        else:
            r = app.invoke(Command(resume=default_decision(p)), cfg)
    assert ex.calls["Task_DraftRepair"] == 2, "approve-after-reject replay re-invoked the capability"
    assert r["outcome"] == "End_Resolved"


class NonDeterministicExecutor:
    """Makes the draft_repair output vary per call by tagging its free-text ``justification`` with
    the call number (schema-valid, unlike an extra key). So a re-invoke on resume would commit a
    DIFFERENT artifact than the human reviewed — making the replay hazard observable (the
    deterministic simulation hides it). Phase 2.0."""

    def __init__(self, memo=None, memoize=True) -> None:
        self._inner = InProcessExecutor()
        self._memo = memo
        self._memoize = memoize and memo is not None
        self.calls: Dict[str, int] = {}

    def execute(self, descriptor, inputs, ctx: ExecutionContext) -> Dict[str, Any]:
        from app.engine.executor.memo import memoized_execute

        def run():
            eid = (ctx.extras or {}).get("element_id", descriptor.capability_id)
            n = self.calls[eid] = self.calls.get(eid, 0) + 1
            base = self._inner.execute(descriptor, inputs, ctx)
            outs = {}
            for k, v in (base.get("outputs") or {}).items():
                if isinstance(v, dict) and isinstance(v.get("justification"), str):
                    outs[k] = {**v, "justification": f"{v['justification']} [draft #{n}]"}
                else:
                    outs[k] = v
            return {**base, "outputs": outs}

        return memoized_execute(memo=self._memo, enabled=self._memoize, inputs=inputs, ctx=ctx, run=run)


def test_native_memoization_on_by_default():
    # ADR-027 Phase 2.0: the native executor memoizes out of the box (store auto-defaulted).
    from app.engine.executor import build_executor

    ex = build_executor(settings.model_copy(update={"EXECUTION_MODE": "native", "MEMOIZE_CAPABILITIES": True}))
    assert getattr(ex, "_memoize") is True
    assert getattr(ex, "_memo") is not None


def test_nondeterministic_capability_resume_commits_reviewed_artifact():
    memo = InMemoryMemoStore()
    ex = NonDeterministicExecutor(memo=memo, memoize=True)
    app = _graph(ex)
    cfg = {"configurable": {"thread_id": "pi-nondet"}}

    payload, r = _first_gate_of(app, cfg, _initial(), "Task_DraftRepair")
    reviewed = payload["artifacts"][0]["data"]
    assert "[draft #1]" in reviewed["justification"]

    r = app.invoke(Command(resume={"decision": "approve", "decided_by": role_user(payload.get("role"))}), cfg)
    while "__interrupt__" in r:
        p = r["__interrupt__"][0].value
        r = app.invoke(Command(resume=default_decision(p)), cfg)

    # Memo served the reviewed (#1) artifact — NOT a re-invoked (#2) one.
    assert "[draft #1]" in r["artifacts"]["repair"]["justification"]
    assert ex.calls["Task_DraftRepair"] == 1


def test_nondeterministic_reject_reruns_and_commits_new_artifact():
    memo = InMemoryMemoStore()
    ex = NonDeterministicExecutor(memo=memo, memoize=True)
    app = _graph(ex)
    cfg = {"configurable": {"thread_id": "pi-nondet-rej"}}

    payload, r = _first_gate_of(app, cfg, _initial(), "Task_DraftRepair")
    r = app.invoke(Command(resume={"decision": "reject", "decided_by": role_user(payload.get("role"))}), cfg)
    assert ex.calls["Task_DraftRepair"] == 2  # reject genuinely re-ran (fresh attempt)

    while "__interrupt__" in r:
        p = r["__interrupt__"][0].value
        if p["element_id"] == "Task_DraftRepair":
            r = app.invoke(Command(resume={"decision": "approve", "decided_by": role_user(p.get("role"))}), cfg)
        else:
            r = app.invoke(Command(resume=default_decision(p)), cfg)
    assert "[draft #2]" in r["artifacts"]["repair"]["justification"]  # the re-produced artifact committed


def test_memo_is_scoped_per_instance():
    memo = InMemoryMemoStore()
    # Same element + inputs but different process_instance_id must not collide.
    ih = inputs_hash({"a": 1})
    memo.put("pi-A", "El", ih, 0, {"art": {"v": "A"}}, None)
    memo.put("pi-B", "El", ih, 0, {"art": {"v": "B"}}, None)
    assert memo.get("pi-A", "El", ih, 0)["outputs"]["art"]["v"] == "A"
    assert memo.get("pi-B", "El", ih, 0)["outputs"]["art"]["v"] == "B"
    assert memo.get("pi-C", "El", ih, 0) is None


def test_native_byte_identical_with_memoize_off():
    # Flag off (default): memo store present but disabled → capability runs each replay, and
    # the committed artifacts/outcome match the plain InProcessExecutor path exactly.
    plain = _graph(InProcessExecutor())
    off = _graph(CountingExecutor(memo=InMemoryMemoStore(), memoize=False))
    from tests._wire import drive
    a, _ = drive(plain, {"configurable": {"thread_id": "pi-x"}}, _initial())
    b, _ = drive(off, {"configurable": {"thread_id": "pi-y"}}, _initial())
    assert a["artifacts"] == b["artifacts"]
    assert a["outcome"] == b["outcome"] == "End_Resolved"
