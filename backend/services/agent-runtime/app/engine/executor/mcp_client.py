# app/engine/executor/mcp_client.py
"""MCP client abstraction for the capability-worker (ADR-020 Part D; ADR-024).

The MCP capability is now **self-descriptive**: the descriptor's `runtime` carries the server
`endpoint`, `transport`, and `headers` directly (ADR-024), so the client no longer resolves a
`server_key` against a registry file — it POSTs a standard **MCP `tools/call`** JSON-RPC
request to the endpoint from the descriptor.

Two implementations:
  * ``HttpMcpClient`` — POSTs `tools/call` to the given `endpoint` with the given `headers`
    (non-secret headers or resolved secret-refs). The MCP protocol itself is an open standard;
    the exact streamable-http framing is ``# [confirm]`` against the target server. Exercised
    by the env-gated integration test against a stub MCP server.
  * ``StubMcpClient`` — deterministic, in-process, no network. Exercises the worker's real MCP
    *code path* (dispatch → client → tool result → artifact) in unit/dev without a server, and
    keeps ``list_provider: stub`` (no real OFAC): a creditor name containing ``SANCTIONED``
    returns a hit, mirroring the simulation capability.

Neither performs a real sanctions-list lookup — Phase 3b delivers the real MCP **transport**,
not a real list (design §5 / ADR-019).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Protocol

logger = logging.getLogger(__name__)

_SANCTION_MARKER = "SANCTIONED"


def _screen_party_result(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a screening_result artifact from an envelope — the stub `screen_party` tool
    output (no real list; marker-based, matching the simulation capability)."""
    creditor_name = (envelope.get("payment", {}) or {}).get("creditor", {}).get("name", "")
    hit = _SANCTION_MARKER in creditor_name.upper()
    verdict = "hit" if hit else "clean"
    return {
        "verdict": verdict,
        "party_results": [{
            "party": "creditor", "name": creditor_name, "result": verdict,
            "score": 0.97 if hit else 0.01,
        }],
        "list_refs": ["OFAC-SDN", "EU-CFSP"],
    }


class McpClient(Protocol):
    async def call_tool(
        self, *, endpoint: str, tool: str, arguments: Dict[str, Any],
        transport: Optional[str], headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        ...


class StubMcpClient:
    """Deterministic in-process MCP stand-in (unit/dev). No network, no real list."""

    async def call_tool(self, *, endpoint, tool, arguments, transport, headers=None):
        envelope = (arguments or {}).get("envelope", {})
        logger.info("StubMcpClient: %s/%s (transport=%s) — stub list, no OFAC", endpoint, tool, transport)
        return _screen_party_result(envelope)


class HttpMcpClient:
    """Calls the MCP server at the descriptor's ``endpoint`` (ADR-024).

    Performs a standard **MCP `tools/call`** JSON-RPC POST. ``headers`` are non-secret headers
    or resolved secret-refs (OpenShell may broker credentials gateway-side); we never hold a raw
    token in the descriptor. ``# [confirm]`` the exact streamable-http framing (SSE vs plain
    JSON) and result envelope against the target server.
    """

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    async def call_tool(self, *, endpoint, tool, arguments, transport, headers=None):
        hdrs = {"content-type": "application/json", "accept": "application/json"}
        hdrs.update(headers or {})  # non-secret headers / resolved secret-refs
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        import httpx

        async with httpx.AsyncClient(timeout=self._timeout) as http:
            resp = await http.post(endpoint, json=payload, headers=hdrs)
            resp.raise_for_status()
            body = resp.json()
        if "error" in body:
            raise RuntimeError(f"MCP tool error: {body['error']}")
        # MCP tools/call returns result.structuredContent (or content[].json/text). We accept
        # a structured screening_result artifact. [confirm] exact result envelope per server.
        result = body.get("result", {})
        structured = result.get("structuredContent") or result.get("structured_content")
        if isinstance(structured, dict):
            return structured
        # Fallback: first JSON content block.
        for block in result.get("content", []) or []:
            if isinstance(block, dict) and isinstance(block.get("json"), dict):
                return block["json"]
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                try:
                    return json.loads(block["text"])
                except Exception:  # noqa: BLE001
                    continue
        raise RuntimeError(f"MCP tool '{tool}' returned no structured result")


def build_mcp_client(settings) -> McpClient:
    """Worker-side MCP client: the real HTTP client (calls the descriptor's endpoint). Tests
    and dev pass ``StubMcpClient()`` explicitly; simulation-gating happens in the caller."""
    return HttpMcpClient()
