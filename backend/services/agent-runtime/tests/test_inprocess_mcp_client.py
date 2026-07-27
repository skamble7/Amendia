# tests/test_inprocess_mcp_client.py
"""ADR-047 D2 — the in-process MCP harness (the unblocker for the seed re-home).

An MCP-backed capability must be able to run end-to-end **in-process**, without a live server: the executor
brokers `mcp` caps through an injected client, and `InProcessMcpClient` dispatches `tools/call` to in-process
tool callables. This is what lets a re-onboarded (skill→mcp) seed pack execute in the non-e2e suite. The tool
behaviours are supplied by the caller (a fixture / the server's tool library) — the platform image carries none.
"""
from __future__ import annotations

import pytest

from app.engine.bundle import PackBundle
from app.engine.executor import InProcessExecutor
from app.engine.executor.base import CapabilityBusinessError, ExecutionContext
from app.engine.executor.mcp_client import InProcessMcpClient
from app.config import settings as app_settings
from tests._wire import make_envelope

_CAP = "cap.payment.sanctions_screen"   # the seed's one mcp cap (tool: screen_party), read_only


def _bundle():
    return PackBundle.from_seed_dir(app_settings.SEED_DIR)


def _ctx(bundle, *, simulation=True):
    return ExecutionContext(envelope=make_envelope("AC01"), mode="execute", simulation=simulation,
                            extras={"output_schemas": {}, "element_id": "El"})


def test_injected_mcp_client_wins_over_simulation_fallback():
    # even in simulation mode, an injected client executes the mcp cap (the D2 harness) — the artifact comes
    # from the in-process tool, NOT the paired simulation skill.
    b = _bundle()
    seen = {}

    def fake_screen(arguments):
        seen["args"] = arguments
        return {"verdict": "clean", "party_results": [{"party": "creditor", "result": "clean"}],
                "list_refs": ["MARKER-IN-PROCESS"]}

    client = InProcessMcpClient({"screen_party": fake_screen})
    out = InProcessExecutor(mcp_client=client).execute(b.descriptors[_CAP], {"repair": {}}, _ctx(b))
    art = out["outputs"]["art.compliance.screen_party_output"]
    assert art["list_refs"] == ["MARKER-IN-PROCESS"]   # produced by the in-process tool, not the sim
    assert seen.get("args") is not None                # the client actually dispatched tools/call


def test_no_client_fails_closed():
    # ADR-047 D2: there is NO simulation fallback. An `mcp` cap with no injected client cannot make its
    # tool call, so it fails closed (rather than silently substituting a per-process simulation skill).
    b = _bundle()
    from app.engine.executor.base import CapabilityError
    with pytest.raises(CapabilityError, match="MCP client"):
        InProcessExecutor().execute(b.descriptors[_CAP], {"repair": {}}, _ctx(b))


def test_inprocess_client_maps_isError_to_business_error():
    # ADR-035: a tool returning a full MCP result with isError+error_code is a MODELED business error.
    b = _bundle()

    def hit_tool(arguments):
        return {"isError": True, "structuredContent": {"error_code": "SCREENING_HIT", "verdict": "hit"}}

    client = InProcessMcpClient({"screen_party": hit_tool})
    with pytest.raises(CapabilityBusinessError) as ei:
        InProcessExecutor(mcp_client=client).execute(b.descriptors[_CAP], {"repair": {}}, _ctx(b))
    assert ei.value.error_code == "SCREENING_HIT"


def test_unknown_tool_fails_closed():
    b = _bundle()
    from app.engine.executor.base import CapabilityError
    client = InProcessMcpClient({})   # no tools registered
    with pytest.raises(CapabilityError):
        InProcessExecutor(mcp_client=client).execute(b.descriptors[_CAP], {"repair": {}}, _ctx(b))
