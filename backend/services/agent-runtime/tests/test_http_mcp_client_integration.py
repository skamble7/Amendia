# tests/test_http_mcp_client_integration.py
"""Integration — the runtime's SDK-backed ``HttpMcpClient`` against a REAL FastMCP server (ADR-047 D2 §5).

Spins up the ``wire-transfer-exception`` MCP server (the exact server the live stack runs) in-process on an
ephemeral port and drives ``HttpMcpClient`` through the full transport the ``mcp`` SDK owns — the ``/mcp`` →
``/mcp/`` redirect, streamable-HTTP / SSE framing, and the session handshake — asserting real tools return
structured artifacts and a tool-level error is handled over the wire. This is the guard the in-process double
can't give: it exercises the actual protocol that broke the live stack (a hand-rolled client passed its mocks
while failing here). After consolidating on the SDK, a server that onboards cleanly executes cleanly.
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from app.engine.executor.base import CapabilityBusinessError
from app.engine.executor.mcp_client import HttpMcpClient

# Import the real server app (same sys.path bridge tests/_mcp_server_tools uses for its handlers).
_SERVER_SRC = Path(__file__).resolve().parents[4] / "mcp_stub" / "servers" / "wire_transfer_exception" / "src"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

try:
    import uvicorn
    from wire_transfer_exception_mcp.server import create_app
    _AVAILABLE = True
except Exception:  # pragma: no cover - environment guard
    _AVAILABLE = False

pytestmark = pytest.mark.skipif(not _AVAILABLE, reason="wire-transfer MCP server / uvicorn not importable")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def mcp_endpoint():
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):  # up to ~10s for startup
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "MCP server did not start"
    try:
        yield f"http://127.0.0.1:{port}/mcp"  # NOTE: no trailing slash — the server 307s to /mcp/
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.asyncio
async def test_real_server_screen_party_returns_structured_artifact(mcp_endpoint):
    out = await HttpMcpClient().call_tool(
        endpoint=mcp_endpoint, tool="screen_party",
        arguments={"party": {"name": "SANCTIONED HOLDINGS"}}, transport="streamable_http")
    assert out["status"] == "hit"
    assert out["matched_lists"]


@pytest.mark.asyncio
async def test_real_server_enrich_returns_structured_artifact(mcp_endpoint):
    out = await HttpMcpClient().call_tool(
        endpoint=mcp_endpoint, tool="enrich_investigation",
        arguments={"envelope": {"exception_id": "EXC-IT"}, "exception_id": "EXC-IT"},
        transport="streamable_http")
    assert isinstance(out, dict) and out.get("exception_id") == "EXC-IT"


@pytest.mark.asyncio
async def test_real_server_assess_honors_resolution_outcome(mcp_endpoint):
    # The rework-loop terminator, over the REAL wire: the server VALIDATES arguments against the tool's CLOSED
    # inputSchema (the in-process handler map does not) — so `resolution` must be a declared field AND the
    # handler must honour it. This guards the exact live/harness divergence that made the loop spin: the fix is
    # the analyst's explicit resolution outcome, NOT a field on the LLM-drafted rfi it can auto-fill.
    client = HttpMcpClient()

    async def assess(args):
        r = await client.call_tool(endpoint=mcp_endpoint, tool="assess_beneficiary",
                                   arguments=args, transport="streamable_http")
        return r["repair_verdict"]

    # first pass — resolution null (as the pack's optional input_map source sends it): reason codes drive.
    assert await assess({"reason_codes": ["BE04"], "resolution": None}) == "needs_info"
    # after Obtain-Info — the analyst's explicit outcome is the terminal verdict (both directions).
    assert await assess({"reason_codes": ["BE04"], "resolution": "resolved"}) == "repairable"
    assert await assess({"reason_codes": ["BE04"], "resolution": "cannot_obtain"}) == "unrepairable"


@pytest.mark.asyncio
async def test_real_server_tool_error_is_handled_over_the_wire(mcp_endpoint):
    # A tool-level failure (unknown tool → the server's handler raises) surfaces over the real transport as
    # either a modeled business error (isError → ADR-035) or a technical RuntimeError — never an unhandled
    # crash. The deterministic isError → error_code mapping is covered by the _result_to_artifact unit tests.
    with pytest.raises((CapabilityBusinessError, RuntimeError)):
        await HttpMcpClient().call_tool(endpoint=mcp_endpoint, tool="does_not_exist",
                                        arguments={}, transport="streamable_http")
