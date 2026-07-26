# app/engine/executor/mcp_client.py
"""MCP client abstraction for the capability-worker (ADR-020 Part D; ADR-024).

The MCP capability is **self-descriptive**: the descriptor's `runtime` carries the server `endpoint`,
`transport`, and `headers` directly (ADR-024), so the client dispatches a standard **MCP `tools/call`** to
the endpoint from the descriptor — no registry-file `server_key` resolution.

Two implementations:
  * ``HttpMcpClient`` — the real client, built on the **official ``mcp`` SDK** (``streamablehttp_client`` /
    ``sse_client`` + ``ClientSession``), the SAME primitives the process-registry onboarding introspector
    uses. The SDK owns the transport: redirects, streamable-HTTP / SSE framing, and protocol negotiation. A
    server that onboards cleanly therefore executes cleanly *by construction* — one MCP client for the
    platform, not two hand-rolled variants that can silently diverge (ADR-047 D2 §5).
  * ``InProcessMcpClient`` (ADR-047 D2) — deterministic, in-process, no network. Dispatches ``tools/call`` to
    caller-supplied in-process tool callables (a fixture or the MCP server's own tool library), so an
    MCP-backed pack runs end-to-end in unit/dev without a live server. The platform image carries **no** tool
    behaviour of its own — the client is domain-neutral.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any, Dict, Optional, Protocol

from app.engine.executor.base import CapabilityBusinessError

logger = logging.getLogger(__name__)

# ADR-035: fallback code when a tool sets ``isError: true`` but carries no conventional
# ``error_code``. Keeping it a *business* error (not technical) honours MCP semantics — an
# ``isError`` result is a tool-level, domain outcome (distinct from a JSON-RPC transport error)
# — so a catch-all error boundary can still catch it (else it falls through to FAILURE_SINK).
_MCP_TOOL_ERROR = "MCP_TOOL_ERROR"


def _result_to_artifact(result: Any, tool: str) -> Dict[str, Any]:
    """Map an SDK ``CallToolResult`` (``.isError`` / ``.structuredContent`` / ``.content``) to the tool's
    structured artifact, applying the ADR-035 business-error mapping. A modeled business error
    (``isError`` + a conventional ``error_code``) raises :class:`CapabilityBusinessError`; a normal result
    returns its ``structuredContent`` (or the first parseable JSON content block)."""
    structured = getattr(result, "structuredContent", None)
    structured = structured if isinstance(structured, dict) else None
    # Normalize the SDK's typed content blocks (TextContent has ``.text``, a JSON string) into the
    # ``{"json": ...}`` shape ``_raise_if_business_error`` + the fallback below already understand.
    content_dicts: list = []
    for block in (getattr(result, "content", None) or []):
        text = getattr(block, "text", None)
        if isinstance(text, str):
            try:
                content_dicts.append({"json": json.loads(text)})
            except json.JSONDecodeError:
                content_dicts.append({"text": text})
    view = {"isError": bool(getattr(result, "isError", False)),
            "structuredContent": structured, "content": content_dicts}
    _raise_if_business_error(view, tool)  # ADR-035: isError + error_code → CapabilityBusinessError
    if structured is not None:
        return structured
    for cd in content_dicts:
        if isinstance(cd.get("json"), dict):
            return cd["json"]
    raise RuntimeError(f"MCP tool '{tool}' returned no structured result")


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
    """Calls the MCP server at the descriptor's ``endpoint`` via the official ``mcp`` SDK (ADR-024).

    Opens a session with ``streamablehttp_client`` (or ``sse_client`` for the ``sse`` transport), runs the
    protocol handshake (``ClientSession.initialize``), and invokes ``call_tool`` — the SAME connection setup
    the process-registry introspector uses, so the SDK owns redirects, SSE framing, and negotiation (no
    hand-rolled 307/Accept handling). ``headers`` are non-secret headers or resolved secret-refs (OpenShell
    may broker credentials gateway-side); we never hold a raw token in the descriptor.

    Transport / protocol / handshake failures surface as a technical ``RuntimeError`` (the caller maps it to a
    ``CapabilityError``); a tool-level ``isError`` with a conventional ``error_code`` is a MODELED business
    error → :class:`CapabilityBusinessError` → the BPMN error boundary (ADR-035), unchanged.
    """

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    async def call_tool(self, *, endpoint, tool, arguments, transport, headers=None):
        from mcp import ClientSession
        if transport == "sse":
            from mcp.client.sse import sse_client as _open
        else:
            from mcp.client.streamable_http import streamablehttp_client as _open

        hdrs = dict(headers or {})  # non-secret headers / resolved secret-refs
        try:
            async with _open(endpoint, headers=hdrs) as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        tool, arguments or {},
                        read_timeout_seconds=timedelta(seconds=self._timeout),
                    )
        except Exception as exc:  # noqa: BLE001 — transport/protocol/handshake → technical failure
            raise RuntimeError(f"MCP call to {endpoint} tool '{tool}' failed: {exc}") from exc
        # ADR-035 mapping runs OUTSIDE the try so a modeled CapabilityBusinessError propagates unwrapped.
        return _result_to_artifact(result, tool)


def build_mcp_client(settings) -> McpClient:
    """Worker-side MCP client: the SDK-backed :class:`HttpMcpClient` (calls the descriptor's endpoint). Tests
    and dev inject an :class:`InProcessMcpClient` explicitly (ADR-047 D2); simulation-gating is in the caller."""
    return HttpMcpClient()
