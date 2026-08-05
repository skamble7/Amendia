# tests/test_capability_worker_broker.py
"""ADR-020 — the in-sandbox capability-worker + broker request/reply substrate.

All unit-level (no RabbitMQ, no OpenShell): the ``InMemoryBrokerTransport`` drives the worker
runner in-process. Covers shared-core parity, broker correlation/timeout/idempotency,
secrets-not-on-the-wire, B/D/E realized in the worker, memo+broker interplay, and the
native-vs-nemoclaw(broker) invariance.
"""
from __future__ import annotations

import json
from typing import Any, Dict

import pytest
from jsonschema import Draft202012Validator
from langgraph.checkpoint.memory import MemorySaver

from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.compiler import compile_graph
from app.engine.executor import SandboxedExecutor
from app.engine.executor import dispatch
from app.engine.executor.base import CapabilityError, ExecutionContext
from app.engine.executor.memo import InMemoryMemoStore
from app.engine.executor.openshell import (
    BrokerOpenShellClient,
    CapabilityRunSpec,
    InMemoryBrokerTransport,
    spec_to_job,
)
from app.engine.executor.worker_runner import run_job
from app.engine.state import initial_state
from tests._stub_stack import stub_executor, stub_run_job
from tests._wire import default_decision, drive, make_envelope, role_user
from langgraph.types import Command


def _bundle() -> PackBundle:
    return PackBundle.from_seed_dir(settings.SEED_DIR)


def _job_for(cap_id: str, inputs: Dict[str, Any], *, simulation=True, mode="execute",
             envelope=None, mcp_arguments=None):
    b = _bundle()
    d = b.descriptors[cap_id]
    output_schemas = {}
    for o in d.outputs:
        akey = o.model_dump(by_alias=True)["schema"].split("@", 1)[0]
        output_schemas[akey] = b.schemas.get(f"{akey}@1.0.0")
    return {
        "request_id": f"req-{cap_id}",
        "spec": {
            "capability_id": cap_id, "kind": d.kind.value, "inputs": inputs,
            "envelope": envelope or make_envelope("AC01"), "output_schemas": output_schemas,
            "mcp_arguments": mcp_arguments,
            "mode": mode, "approved_action_ids": None, "model_config_ref": None,
            "element_id": "El", "process_instance_id": "pi-1", "memo_attempt": 0,
            "simulation": simulation, "egress_policy": None,
            "descriptor": d.model_dump(by_alias=True, mode="json"),
        },
    }


def _ctx(bundle, cap_id, simulation=True):
    d = bundle.descriptors[cap_id]
    output_schemas = {}
    for o in d.outputs:
        akey = o.model_dump(by_alias=True)["schema"].split("@", 1)[0]
        output_schemas[akey] = bundle.schemas.get(f"{akey}@1.0.0")
    return ExecutionContext(envelope=make_envelope("AC01"), mode="execute", simulation=simulation,
                            extras={"output_schemas": output_schemas, "element_id": "El"})


# --------------------------------------------------------------------------- #
# Shared-core parity
# --------------------------------------------------------------------------- #
def test_shared_core_parity_in_process_vs_worker():
    # ADR-047 D2: native (stub_executor) and worker (stub_run_job) run the SAME injected stub stack over the
    # shared core → byte-identical outputs. Transparency by construction, no per-worker simulation.
    b = _bundle()
    for cap in ("cap.payment.enrich_investigation", "cap.payment.assess_beneficiary",
                "cap.payment.sanctions_screen"):
        inputs = {"dossier": {}, "beneficiary": {}}
        in_proc = stub_executor().execute(b.descriptors[cap], inputs, _ctx(b, cap))
        worker = stub_run_job(_job_for(cap, inputs))
        assert worker["ok"] is True
        assert worker["result"]["outputs"] == in_proc["outputs"], f"parity mismatch for {cap}"


# --------------------------------------------------------------------------- #
# Broker request/reply — correlation, timeout, idempotency/retry, clean failure
# --------------------------------------------------------------------------- #
def _spec(cap_id="cap.payment.sanctions_screen", *, simulation=True, timeout=None,
          idempotent=False, max_retries=0) -> CapabilityRunSpec:
    b = _bundle()
    d = b.descriptors[cap_id]
    return CapabilityRunSpec(
        capability_id=cap_id, kind=d.kind.value, inputs={}, envelope=make_envelope("AC01"),
        output_schemas={}, element_id="El", process_instance_id="pi-1", simulation=simulation,
        descriptor=d, timeout_seconds=timeout, idempotent=idempotent, max_retries=max_retries,
    )


@pytest.mark.asyncio
async def test_broker_roundtrip_returns_sandbox_result():
    client = BrokerOpenShellClient(InMemoryBrokerTransport(stub_run_job))
    res = await client.run_capability(_spec())
    assert res.outputs["art.compliance.screen_party_output"]["status"] == "clear"
    assert res.otlp_trace_id.startswith("otlp-worker-")


@pytest.mark.asyncio
async def test_broker_timeout_surfaces_clean_failure():
    # A transport that never replies → the client times out and raises CapabilityError.
    client = BrokerOpenShellClient(InMemoryBrokerTransport(run_job, drop=True))
    with pytest.raises(CapabilityError, match="timed out"):
        await client.run_capability(_spec(timeout=0.05))


@pytest.mark.asyncio
async def test_broker_retries_only_when_idempotent():
    # Worker returns an error reply; idempotent → retried up to max_retries+1.
    def failing(job):
        return {"request_id": job["request_id"], "ok": False, "error": "boom"}

    t_idem = InMemoryBrokerTransport(failing)
    with pytest.raises(CapabilityError):
        await BrokerOpenShellClient(t_idem).run_capability(
            _spec(idempotent=True, max_retries=2, timeout=1))
    assert t_idem.calls == 3  # 1 + 2 retries

    t_non = InMemoryBrokerTransport(failing)
    with pytest.raises(CapabilityError):
        await BrokerOpenShellClient(t_non).run_capability(
            _spec(idempotent=False, max_retries=2, timeout=1))
    assert t_non.calls == 1  # no retry for non-idempotent


@pytest.mark.asyncio
async def test_broker_correlates_request_id_deterministically():
    # Same (instance, element, inputs, attempt) → same request_id (idempotency handle).
    captured = []

    def capture(job):
        captured.append(job["request_id"])
        return stub_run_job(job)

    client = BrokerOpenShellClient(InMemoryBrokerTransport(capture))
    await client.run_capability(_spec())
    await client.run_capability(_spec())
    assert captured[0] == captured[1]
    assert captured[0].startswith("pi-1:El:")


# --------------------------------------------------------------------------- #
# Secrets never cross the wire
# --------------------------------------------------------------------------- #
def test_secrets_not_on_the_wire():
    b = _bundle()
    d = b.descriptors["cap.payment.draft_repair"].model_copy(deep=True)
    d.runtime.model_config_key = "dev.llm.nemoclaw.nim"
    spec = CapabilityRunSpec(
        capability_id=d.capability_id, kind="llm", inputs={}, envelope=make_envelope("AC01"),
        model_config_ref="dev.llm.nemoclaw.nim", descriptor=d,
    )
    job = spec_to_job(spec)
    blob = json.dumps(job)
    assert job["model_config_ref"] == "dev.llm.nemoclaw.nim"      # a ref, not a key
    # No provider key material anywhere in the serialized job.
    for needle in ("sk-", "AKIA", "api_key", "secret_key", "AWS_SECRET"):
        assert needle not in blob


# --------------------------------------------------------------------------- #
# D — real MCP transport in the worker (stub client, stub list)
# --------------------------------------------------------------------------- #
def test_worker_mcp_uses_client_not_sim():
    # ADR-047 D2: an `mcp` cap always goes through the MCP client (no simulation fallback). The worker
    # makes the SAME tool call as native — here the input_map's `party` (payment.creditor) drives the
    # marker-based `screen_party` stub to a `hit`, proving the real MCP transport path is exercised.
    job = _job_for("cap.payment.sanctions_screen", {}, simulation=False,
                   envelope=make_envelope("AC01", creditor_name="SANCTIONED HOLDINGS"),
                   mcp_arguments={"party": {"name": "SANCTIONED HOLDINGS"}})
    reply = stub_run_job(job)
    assert reply["ok"] is True
    screening = reply["result"]["outputs"]["art.compliance.screen_party_output"]
    assert screening["status"] == "hit"           # marker-based stub, real MCP transport path
    assert "real MCP" in reply["result"]["log"]


# --------------------------------------------------------------------------- #
# B — llm in the worker routes through run_real_llm (mocked, no inference)
# --------------------------------------------------------------------------- #
def test_worker_llm_routes_through_run_real_llm(monkeypatch):
    # The production llm path in the worker (NOT stub_inference): routes through run_real_llm. The provider
    # call is mocked (no inference); the returned artifact is a schema-valid stub (ADR-047 D2 — no domain
    # capability code to import).
    b = _bundle()
    from app.engine.executor.stub_inference import stub_from_schema
    schema = b.schemas["art.payment.repair_instruction@1.0.0"]
    valid = stub_from_schema(schema)

    def fake_run_real_llm(*, capability_id, targets, ref, inputs, envelope, error_codes=None, cancel=None,
                          title=None, description=None):
        return ({akey: valid for akey, _ in targets}, "nemoclaw", "nemotron-3-ultra")

    monkeypatch.setattr(dispatch, "run_real_llm", fake_run_real_llm)
    reply = run_job(_job_for("cap.payment.draft_repair", {"beneficiary": {}}, simulation=False))
    assert reply["ok"] is True
    assert "art.payment.repair_instruction" in reply["result"]["outputs"]
    assert "real LLM" in reply["result"]["log"]


# --------------------------------------------------------------------------- #
# End-to-end AC01 through the broker + worker (no fake, no gateway)
# --------------------------------------------------------------------------- #
def _broker_graph(memo=None, memoize=False, counter=None):
    handler = stub_run_job
    if counter is not None:
        def counting(job):
            el = job["spec"].get("element_id")
            counter[el] = counter.get(el, 0) + 1
            return stub_run_job(job)
        handler = counting
    client = BrokerOpenShellClient(InMemoryBrokerTransport(handler))
    ex = SandboxedExecutor(client, fallback=stub_executor(), memo=memo, memoize=memoize)
    return compile_graph(_bundle(), ex, simulation=True, checkpointer=MemorySaver())


def _initial(exception_id="EXC-BRK"):
    return initial_state(envelope=make_envelope("AC01", exception_id=exception_id),
                         trace={"correlation_id": exception_id},
                         pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"})


def test_ac01_runs_to_resolved_through_broker_worker():
    app = _broker_graph()
    cfg = {"configurable": {"thread_id": "pi-brk-ac01"}}
    result, gates = drive(app, cfg, _initial())
    assert result["outcome"] == "End_Resolved"
    assert set(result["artifacts"]) >= {"dossier", "beneficiary", "repair", "screening", "resolution"}
    cap_entries = [e for e in result["actor_log"] if e["kind"] == "capability" and "exec_meta" in e]
    traced = {e["element_id"]: e["exec_meta"]["otlp_trace_id"] for e in cap_entries}
    assert "Task_DraftRepair" in traced and "Task_SanctionsRescreen" in traced
    # ADR-058: the worker now emits a REAL OTLP span parented to the node span's traceparent, so the
    # ids are 32-char hex trace ids (unified into the instance trace) — not the old `otlp-worker-` marker.
    assert all(len(t) == 32 and int(t, 16) != 0 for t in traced.values())


def test_native_vs_broker_worker_invariance():
    native = compile_graph(_bundle(), stub_executor(), simulation=True, checkpointer=MemorySaver())
    broker = _broker_graph()
    n, _ = drive(native, {"configurable": {"thread_id": "pi-n"}}, _initial("EXC-INV2"))
    s, _ = drive(broker, {"configurable": {"thread_id": "pi-s"}}, _initial("EXC-INV2"))
    assert n["artifacts"] == s["artifacts"]
    assert n["outcome"] == s["outcome"] == "End_Resolved"


def test_memo_and_broker_interplay_no_reinvoke_on_resume():
    counter: Dict[str, int] = {}
    app = _broker_graph(memo=InMemoryMemoStore(), memoize=True, counter=counter)
    cfg = {"configurable": {"thread_id": "pi-brk-memo"}}
    # Reach Task_DraftRepair (review_after), approving prior gates.
    r = app.invoke(_initial("EXC-MEMO-BRK"), cfg)
    while "__interrupt__" in r:
        p = r["__interrupt__"][0].value
        if p["element_id"] == "Task_DraftRepair":
            break
        r = app.invoke(Command(resume=default_decision(p)), cfg)
    assert counter["Task_DraftRepair"] == 1
    # Approve → resume replays the node; the worker must NOT be re-invoked (memo hit).
    r = app.invoke(Command(resume={"decision": "approve", "decided_by": role_user(p.get("role"))}), cfg)
    while "__interrupt__" in r:
        p2 = r["__interrupt__"][0].value
        r = app.invoke(Command(resume=default_decision(p2)), cfg)
    assert counter["Task_DraftRepair"] == 1, "worker re-invoked on resume (memo+broker broken)"
    assert r["outcome"] == "End_Resolved"
