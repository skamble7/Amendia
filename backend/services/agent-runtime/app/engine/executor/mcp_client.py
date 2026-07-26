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
  * ``InProcessMcpClient`` (ADR-047 D2) — deterministic, in-process, no network. Dispatches
    ``tools/call`` to caller-supplied in-process tool callables (a fixture or the MCP server's own
    tool library), so an MCP-backed pack runs end-to-end in unit/dev without a live server. The
    platform image carries **no** tool behaviour of its own — the client is domain-neutral.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Protocol

from app.engine.executor.base import CapabilityBusinessError

logger = logging.getLogger(__name__)

# ADR-035: fallback code when a tool sets ``isError: true`` but carries no conventional
# ``error_code``. Keeping it a *business* error (not technical) honours MCP semantics — an
# ``isError`` result is a tool-level, domain outcome (distinct from a JSON-RPC transport error)
# — so a catch-all error boundary can still catch it (else it falls through to FAILURE_SINK).
_MCP_TOOL_ERROR = "MCP_TOOL_ERROR"


def _raise_if_business_error(result: Dict[str, Any], tool: str) -> None:
    """ADR-035: map an MCP ``tools/call`` **``result.isError == true``** into a modeled
    :class:`CapabilityBusinessError`.

    The MCP protocol distinguishes a *tool execution error* (``result.isError`` — the tool ran and
    reported a domain failure: payment rejected, screening hit, insufficient info) from a *protocol
    error* (a JSON-RPC ``error`` object / transport failure). The former is exactly a diagram-
    anticipated business error and routes to the BPMN error boundary; the latter stays a technical
    failure (handled by the caller, unchanged). The conventional ``error_code`` is read from
    ``structuredContent.error_code`` (or, for an action-tool acknowledgement, the same field
    alongside ``status: "rejected"``), else the first structured content block; absent any code we
    fall back to :data:`_MCP_TOOL_ERROR` so the outcome is still modeled, never silently technical.

    No-op when ``result`` is not an error result."""
    if not (isinstance(result, dict) and result.get("isError")):
        return
    structured = result.get("structuredContent") or result.get("structured_content")
    detail: Dict[str, Any] = structured if isinstance(structured, dict) else {}
    code = detail.get("error_code") if isinstance(detail, dict) else None
    if not code:
        for block in result.get("content", []) or []:
            if isinstance(block, dict) and isinstance(block.get("json"), dict):
                jd = block["json"]
                if jd.get("error_code"):
                    code, detail = jd["error_code"], jd
                    break
    raise CapabilityBusinessError(str(code) if code else _MCP_TOOL_ERROR, detail=detail or None)


class McpClient(Protocol):
    async def call_tool(
        self, *, endpoint: str, tool: str, arguments: Dict[str, Any],
        transport: Optional[str], headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Return the tool's structured artifact. **May raise** (ADR-035)
        :class:`CapabilityBusinessError` when the MCP ``result.isError`` flag is set with a
        conventional ``error_code`` (a modeled business error routed to a BPMN error boundary),
        distinct from a protocol/transport error which stays a technical ``RuntimeError``."""
        ...


class InProcessMcpClient:
    """ADR-047 D2: a no-network :class:`McpClient` that dispatches ``tools/call`` to **in-process tool
    callables** — the test/dev stand-in for a real MCP server, letting an MCP-backed pack run end-to-end
    without a live server. Domain-neutral: the tool behaviours are supplied by the caller (a fixture or the
    MCP server's own tool library), so the platform image carries none of them.

    ``tools`` maps a tool name → ``fn(arguments: dict) -> dict``. A handler may return either the tool's
    structured artifact directly, or a full MCP ``result`` object (``isError: true`` + a conventional
    ``structuredContent.error_code``) to model a business error — mapped to :class:`CapabilityBusinessError`
    exactly as the HTTP client does (ADR-035). Unknown tools fail closed."""

    def __init__(self, tools: Dict[str, Any]) -> None:
        self._tools = dict(tools)

    async def call_tool(self, *, endpoint, tool, arguments, transport, headers=None):
        fn = self._tools.get(tool)
        if fn is None:
            raise RuntimeError(f"InProcessMcpClient: no in-process tool registered for '{tool}'")
        result = fn(arguments or {})
        # A full MCP result object → apply the ADR-035 business-error mapping, then unwrap the artifact.
        if isinstance(result, dict) and "isError" in result:
            _raise_if_business_error(result, tool)
            structured = result.get("structuredContent") or result.get("structured_content")
            return structured if isinstance(structured, dict) else {}
        return result


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
            # JSON-RPC / protocol error → TECHNICAL failure (not a modeled business error).
            raise RuntimeError(f"MCP tool error: {body['error']}")
        # MCP tools/call returns result.structuredContent (or content[].json/text). We accept the
        # tool's structured artifact. [confirm] exact result envelope per server.
        result = body.get("result", {})
        # ADR-035: a tool-level error (result.isError) with a conventional error_code is a MODELED
        # business error (routes to the BPMN error boundary), distinct from the transport error above.
        _raise_if_business_error(result, tool)
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
    """Worker-side MCP client: the real HTTP client (calls the descriptor's endpoint). Tests and dev
    inject an :class:`InProcessMcpClient` explicitly (ADR-047 D2); simulation-gating is in the caller."""
    return HttpMcpClient()
