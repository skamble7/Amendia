# tests/test_real_business_error.py
"""ADR-035 / Backlog Item A — real (non-simulation) llm / mcp / deep_agent business-error mapping.

Proves that a modeled business error signalled by a *real* capability path — an MCP tool's
``result.isError`` + ``error_code``, or an llm/deep_agent ``{"business_error": {...}}`` object —
raises ``CapabilityBusinessError`` and routes to the BPMN error boundary exactly as the sim path
does (ADR-030), while transport/technical failures still fail technically. Deterministic: fake MCP
client / fake LLM client / fake deep_agent runner, no network, no inference.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver

from amendia_bpmn import parse
from app.config import settings as app_settings
from app.engine.bundle import PackBundle
from app.engine.compiler import FAILED_OUTCOME, compile_graph
from app.engine.executor import dispatch
from app.engine.executor.base import (
    CapabilityBusinessError,
    CapabilityError,
    ExecutionContext,
    business_error_from_object,
)
from app.engine.executor.core import execute_capability
from app.engine.executor.mcp_client import (
    HttpMcpClient,
    StubMcpClient,
    _raise_if_business_error,
)
from app.engine.state import initial_state
from tests._wire import drive, make_envelope

PK, PV = "wire-repair-standard", "1.0.0"
AGENTIC_SEED = str(app_settings.SEED_DIR).replace("wire-repair-standard", "wire-repair-agentic")

MCP_CAP = "cap.payment.sanctions_screen"        # kind=mcp
LLM_CAP = "cap.payment.draft_repair"            # kind=llm
DA_CAP = "cap.payment.assess_beneficiary_agentic"  # kind=deep_agent


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _FakeLLMClient:
    """Minimal polyllm-shaped client: ``chat(messages)`` → an object with ``.text`` / ``.raw``.
    Records the messages it was asked with so a test can assert the prompt."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.seen: list = []

    async def chat(self, messages):
        self.seen.append(messages)
        return SimpleNamespace(text=self._text, raw={"provider": "fake", "model": "fake-1"})


class _BusinessErrorRunner:
    """A deep_agent runner that returns the discriminated business_error object."""

    async def run(self, **kwargs):
        return {"business_error": {"code": "NEEDS_INFO", "detail": {"missing": ["iban"]}}}


class _RaisingRunner:
    """A deep_agent runner that raises CapabilityBusinessError directly."""

    async def run(self, **kwargs):
        raise CapabilityBusinessError("NEEDS_INFO", detail={"missing": ["iban"]})


class _RaisingMcpClient:
    """An MCP client whose transport fails technically (a RuntimeError)."""

    async def call_tool(self, *, endpoint, tool, arguments, transport, headers=None):
        raise RuntimeError("connection reset")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _bundle(seed=None) -> PackBundle:
    return PackBundle.from_seed_dir(seed or app_settings.SEED_DIR)


def _ctx(bundle, cap_id, *, simulation=False, error_codes=None) -> ExecutionContext:
    d = bundle.descriptors[cap_id]
    output_schemas = {}
    for o in d.outputs:
        akey = o.model_dump(by_alias=True)["schema"].split("@", 1)[0]
        output_schemas[akey] = bundle.schemas.get(f"{akey}@1.0.0")
    extras = {"output_schemas": output_schemas, "element_id": "El"}
    if error_codes is not None:
        extras["error_codes"] = error_codes
    return ExecutionContext(envelope=make_envelope("AC01"), mode="execute",
                            simulation=simulation, extras=extras)


def _valid_repair_instruction() -> dict:
    """A schema-valid repair_instruction artifact — reuse the sim capability's own output."""
    from app.capabilities.wire_repair.draft_repair import run
    return run(inputs={"beneficiary": {}}, envelope=make_envelope("AC01"))["outputs"][
        "art.payment.repair_instruction"
    ]


class HybridRealExecutor:
    """Runs the REAL path for a named set of capabilities (with injected fake clients), and the
    deterministic simulation path for everything else — so a single capability can be exercised on
    its real code path inside a full sim graph. Implements the ``Executor`` protocol."""

    def __init__(self, real_caps, *, mcp_client=None, deep_agent_runner=None) -> None:
        self._real = set(real_caps)
        self._mcp = mcp_client
        self._da = deep_agent_runner

    def execute(self, descriptor, inputs, ctx):
        if descriptor.capability_id in self._real:
            return execute_capability(descriptor, inputs, replace(ctx, simulation=False),
                                      mcp_client=self._mcp, deep_agent_runner=self._da)
        return execute_capability(descriptor, inputs, ctx, mcp_client=None)


def _seed_xml() -> str:
    return (Path(app_settings.SEED_DIR) / "wire-repair.bpmn").read_text()


def _xml_with_boundary(*, host, code="PAYMENT_REJECTED", target="End_Returned", catch_all=False) -> str:
    """Attach an error boundary (code → target) to `host`, mirroring test_error_boundary."""
    xml = _seed_xml()
    errdef = f'<bpmn:error id="Err" errorCode="{code}"/>'
    boundary = (
        f'<bpmn:boundaryEvent id="BndErr" attachedToRef="{host}">'
        '<bpmn:errorEventDefinition errorRef="Err"/></bpmn:boundaryEvent>'
        f'<bpmn:sequenceFlow id="Flow_Err" sourceRef="BndErr" targetRef="{target}"/>'
    )
    if catch_all:
        boundary += (
            f'<bpmn:boundaryEvent id="BndAny" attachedToRef="{host}">'
            '<bpmn:errorEventDefinition/></bpmn:boundaryEvent>'
            f'<bpmn:sequenceFlow id="Flow_Any" sourceRef="BndAny" targetRef="{target}"/>'
        )
    xml = xml.replace("</bpmn:process>", boundary + "</bpmn:process>")
    xml = xml.replace("</bpmn:definitions>", errdef + "</bpmn:definitions>")
    return xml


def _graph(xml: str, executor):
    b = PackBundle.from_seed_dir(app_settings.SEED_DIR)
    model, findings = parse(xml, b.manifest.process.process_id, profile="error_boundary")
    errs = [f.code for f in findings if f.severity == "error"]
    assert errs == [], errs
    b.bpmn_model = model
    b.bpmn_xml = xml
    return compile_graph(b, executor, simulation=True, checkpointer=MemorySaver(),
                         profile="error_boundary")


def _initial(reason_codes=("AC01",)):
    env = make_envelope("AC01")
    env["reason_codes"] = list(reason_codes)
    return initial_state(envelope=env, trace={"correlation_id": "c"},
                         pack={"pack_key": PK, "pack_version": PV})


# =========================================================================== #
# Unit: MCP isError → business error (mapping + call_tool + real executor path)
# =========================================================================== #
def test_iserror_structured_content_maps_to_business_error():
    result = {"isError": True, "structuredContent": {"error_code": "PAYMENT_REJECTED", "reason": "rails"}}
    with pytest.raises(CapabilityBusinessError) as ei:
        _raise_if_business_error(result, "screen_party")
    assert ei.value.error_code == "PAYMENT_REJECTED"
    assert ei.value.detail["reason"] == "rails"


def test_iserror_content_block_error_code():
    result = {"isError": True, "content": [{"type": "json", "json": {"error_code": "SCREENING_HIT"}}]}
    with pytest.raises(CapabilityBusinessError) as ei:
        _raise_if_business_error(result, "screen_party")
    assert ei.value.error_code == "SCREENING_HIT"


def test_iserror_without_code_falls_back_to_generic_business_code():
    with pytest.raises(CapabilityBusinessError) as ei:
        _raise_if_business_error({"isError": True}, "screen_party")
    assert ei.value.error_code == "MCP_TOOL_ERROR"


def test_non_error_result_is_a_noop():
    _raise_if_business_error({"structuredContent": {"verdict": "clean"}}, "screen_party")  # no raise


@pytest.mark.asyncio
async def test_stub_client_error_result_raises_business_error():
    client = StubMcpClient(error_result={"isError": True,
                                          "structuredContent": {"error_code": "PAYMENT_REJECTED"}})
    with pytest.raises(CapabilityBusinessError):
        await client.call_tool(endpoint="e", tool="screen_party", arguments={}, transport="streamable_http")


def test_execute_capability_mcp_propagates_business_error_unwrapped():
    b = _bundle()
    d = b.descriptors[MCP_CAP]
    client = StubMcpClient(error_result={"isError": True,
                                         "structuredContent": {"error_code": "PAYMENT_REJECTED"}})
    with pytest.raises(CapabilityBusinessError) as ei:
        execute_capability(d, {}, _ctx(b, MCP_CAP), mcp_client=client)
    assert ei.value.error_code == "PAYMENT_REJECTED"


def test_execute_capability_mcp_technical_error_stays_technical():
    b = _bundle()
    d = b.descriptors[MCP_CAP]
    with pytest.raises(CapabilityError):  # NOT a CapabilityBusinessError
        execute_capability(d, {}, _ctx(b, MCP_CAP), mcp_client=_RaisingMcpClient())


@pytest.mark.asyncio
async def test_http_client_iserror_body_raises_business_error(monkeypatch):
    body = {"jsonrpc": "2.0", "id": 1,
            "result": {"isError": True, "structuredContent": {"error_code": "PAYMENT_REJECTED"}}}
    _install_fake_httpx(monkeypatch, body)
    with pytest.raises(CapabilityBusinessError):
        await HttpMcpClient().call_tool(endpoint="http://x", tool="screen_party",
                                        arguments={}, transport="streamable_http")


@pytest.mark.asyncio
async def test_http_client_jsonrpc_error_stays_technical(monkeypatch):
    body = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "boom"}}
    _install_fake_httpx(monkeypatch, body)
    with pytest.raises(RuntimeError):  # protocol error → technical (caller maps to CapabilityError)
        await HttpMcpClient().call_tool(endpoint="http://x", tool="screen_party",
                                        arguments={}, transport="streamable_http")


def _install_fake_httpx(monkeypatch, body):
    import httpx

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return body

    class _Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


# =========================================================================== #
# Unit: LLM business_error object / normal / non-JSON / prompt threading
# =========================================================================== #
def test_run_real_llm_business_error_object_raises(monkeypatch):
    fake = _FakeLLMClient('{"business_error": {"code": "PAYMENT_REJECTED", "detail": {"why": "x"}}}')
    monkeypatch.setattr(dispatch, "_llm_client", lambda ref: fake)
    with pytest.raises(CapabilityBusinessError) as ei:
        dispatch.run_real_llm(capability_id="c", targets=[("art.k", None)], ref="r",
                              inputs={}, envelope=make_envelope("AC01"),
                              error_codes=["PAYMENT_REJECTED"])
    assert ei.value.error_code == "PAYMENT_REJECTED"
    assert ei.value.detail["why"] == "x"


def test_run_real_llm_normal_artifact_ok(monkeypatch):
    fake = _FakeLLMClient('{"repair_verdict": "repairable"}')
    monkeypatch.setattr(dispatch, "_llm_client", lambda ref: fake)
    produced, provider, model = dispatch.run_real_llm(
        capability_id="c", targets=[("art.k", None)], ref="r",
        inputs={}, envelope=make_envelope("AC01"))
    assert produced["art.k"] == {"repair_verdict": "repairable"}


def test_run_real_llm_non_json_is_technical(monkeypatch):
    fake = _FakeLLMClient("this is not json")
    monkeypatch.setattr(dispatch, "_llm_client", lambda ref: fake)
    with pytest.raises(CapabilityError):  # technical, NOT a business error
        dispatch.run_real_llm(capability_id="c", targets=[("art.k", None)], ref="r",
                              inputs={}, envelope=make_envelope("AC01"))


def test_run_real_llm_threads_error_codes_into_prompt(monkeypatch):
    fake = _FakeLLMClient('{"repair_verdict": "repairable"}')
    monkeypatch.setattr(dispatch, "_llm_client", lambda ref: fake)
    dispatch.run_real_llm(capability_id="c", targets=[("art.k", None)], ref="r",
                          inputs={}, envelope=make_envelope("AC01"),
                          error_codes=["PAYMENT_REJECTED", "SCREENING_HIT"])
    system = fake.seen[0][0]["content"]
    assert "business_error" in system
    assert "PAYMENT_REJECTED" in system and "SCREENING_HIT" in system


def test_run_real_llm_no_error_codes_no_business_error_hint(monkeypatch):
    fake = _FakeLLMClient('{"repair_verdict": "repairable"}')
    monkeypatch.setattr(dispatch, "_llm_client", lambda ref: fake)
    dispatch.run_real_llm(capability_id="c", targets=[("art.k", None)], ref="r",
                          inputs={}, envelope=make_envelope("AC01"))
    assert "business_error" not in fake.seen[0][0]["content"]


def test_business_error_from_object_shapes():
    assert business_error_from_object({"business_error": {"code": "X"}}).error_code == "X"
    assert business_error_from_object({"business_error": {"code": "  "}}) is None  # blank
    assert business_error_from_object({"business_error": {}}) is None              # no code
    assert business_error_from_object({"repair_verdict": "repairable"}) is None    # normal artifact
    assert business_error_from_object("nope") is None


# =========================================================================== #
# Unit: deep_agent business error (returned object + raised)
# =========================================================================== #
def test_deep_agent_business_error_object_raises():
    b = _bundle(AGENTIC_SEED)
    d = b.descriptors[DA_CAP]
    with pytest.raises(CapabilityBusinessError) as ei:
        execute_capability(d, {"dossier": {}}, _ctx(b, DA_CAP),
                           deep_agent_runner=_BusinessErrorRunner())
    assert ei.value.error_code == "NEEDS_INFO"


def test_deep_agent_raised_business_error_propagates_unwrapped():
    b = _bundle(AGENTIC_SEED)
    d = b.descriptors[DA_CAP]
    with pytest.raises(CapabilityBusinessError):  # NOT swallowed into CapabilityError
        execute_capability(d, {"dossier": {}}, _ctx(b, DA_CAP),
                           deep_agent_runner=_RaisingRunner())


# =========================================================================== #
# Graph: a real business error routes to the error boundary (ADR-030 routing)
# =========================================================================== #
def test_real_mcp_business_error_routes_to_boundary():
    client = StubMcpClient(error_result={"isError": True,
                                         "structuredContent": {"error_code": "PAYMENT_REJECTED"}})
    ex = HybridRealExecutor([MCP_CAP], mcp_client=client)
    app = _graph(_xml_with_boundary(host="Task_SanctionsRescreen"), ex)
    result, _ = drive(app, {"configurable": {"thread_id": "rbe-mcp"}}, _initial())
    assert result["outcome"] == "End_Returned" and result["outcome"] != FAILED_OUTCOME
    assert result["boundary"]["Task_SanctionsRescreen"] == {"kind": "error", "code": "PAYMENT_REJECTED"}
    entry = next(e for e in result["actor_log"]
                 if e["element_id"] == "Task_SanctionsRescreen"
                 and e.get("exec_meta", {}).get("business_error"))
    assert entry["exec_meta"]["business_error"] == "PAYMENT_REJECTED"


def test_real_mcp_unmatched_code_goes_to_failure_sink():
    # tool signals PAYMENT_REJECTED but the boundary catches only SOMETHING_ELSE (no catch-all).
    client = StubMcpClient(error_result={"isError": True,
                                         "structuredContent": {"error_code": "PAYMENT_REJECTED"}})
    ex = HybridRealExecutor([MCP_CAP], mcp_client=client)
    app = _graph(_xml_with_boundary(host="Task_SanctionsRescreen", code="SOMETHING_ELSE"), ex)
    result, _ = drive(app, {"configurable": {"thread_id": "rbe-mcp-unmatched"}}, _initial())
    assert result["outcome"] == FAILED_OUTCOME
    assert "PAYMENT_REJECTED" in (result.get("last_error") or "")


def test_real_llm_business_error_routes_to_boundary(monkeypatch):
    fake = _FakeLLMClient('{"business_error": {"code": "PAYMENT_REJECTED", "detail": {}}}')
    monkeypatch.setattr(dispatch, "_llm_client", lambda ref: fake)
    ex = HybridRealExecutor([LLM_CAP])
    app = _graph(_xml_with_boundary(host="Task_DraftRepair"), ex)
    result, _ = drive(app, {"configurable": {"thread_id": "rbe-llm"}}, _initial())
    assert result["outcome"] == "End_Returned" and result["outcome"] != FAILED_OUTCOME
    assert result["boundary"]["Task_DraftRepair"] == {"kind": "error", "code": "PAYMENT_REJECTED"}


def test_real_llm_normal_artifact_takes_normal_flow(monkeypatch):
    import json
    fake = _FakeLLMClient(json.dumps(_valid_repair_instruction()))
    monkeypatch.setattr(dispatch, "_llm_client", lambda ref: fake)
    ex = HybridRealExecutor([LLM_CAP])
    app = _graph(_xml_with_boundary(host="Task_DraftRepair"), ex)
    result, _ = drive(app, {"configurable": {"thread_id": "rbe-llm-normal"}}, _initial())
    assert result["outcome"] == "End_Resolved"
    assert "Task_DraftRepair" not in (result.get("boundary") or {})
