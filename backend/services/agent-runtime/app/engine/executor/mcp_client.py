# app/engine/executor/mcp_client.py
"""MCP client abstraction for the capability-worker (ADR-020 Part D).

The worker resolves an ``mcp`` capability's ``server_key`` via the **in-sandbox MCP registry**
that OpenShell/NemoClaw writes (`nemoclaw <sandbox> mcp add` → `/sandbox/.deepagents/.nemoclaw-mcp.json`,
**confirmed** path per ADR-019) and calls the named tool over the declared transport.

Two implementations:
  * ``RegistryMcpClient`` — reads the registry, resolves the endpoint, and performs a standard
    **MCP `tools/call`** JSON-RPC request over `streamable_http`. The MCP protocol itself is an
    open standard (not a NemoClaw invention); the **registry file shape** is marked
    ``# [confirm]`` against a real `nemoclaw mcp add` output. Exercised only in the env-gated
    integration test against a stub MCP server.
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
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

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
        self, *, server_key: str, tool: str, arguments: Dict[str, Any], transport: Optional[str],
    ) -> Dict[str, Any]:
        ...


class StubMcpClient:
    """Deterministic in-process MCP stand-in (unit/dev). No network, no real list."""

    async def call_tool(self, *, server_key, tool, arguments, transport):
        envelope = (arguments or {}).get("envelope", {})
        logger.info("StubMcpClient: %s/%s (transport=%s) — stub list, no OFAC", server_key, tool, transport)
        return _screen_party_result(envelope)


class RegistryMcpClient:
    """Resolves ``server_key`` from the in-sandbox registry and calls the MCP server.

    The registry file is written by OpenShell/NemoClaw; its exact JSON shape is
    ``# [confirm]`` — we read a tolerant ``{server_key: {"url", "transport", "headers"?}}``
    (also accepts a top-level ``{"servers": {...}}``). Credentials are OpenShell placeholders
    resolved gateway-side; we never hold a raw token.
    """

    def __init__(self, registry_path: str, *, timeout: float = 30.0) -> None:
        self._registry_path = registry_path
        self._timeout = timeout

    def _resolve(self, server_key: str) -> Dict[str, Any]:
        p = Path(self._registry_path)
        if not p.exists():
            raise RuntimeError(f"MCP registry not found at {self._registry_path}")
        data = json.loads(p.read_text(encoding="utf-8"))
        servers = data.get("servers", data) if isinstance(data, dict) else {}
        entry = servers.get(server_key)
        if not entry or "url" not in entry:
            raise RuntimeError(f"MCP server_key '{server_key}' not in registry")
        return entry

    async def call_tool(self, *, server_key, tool, arguments, transport):
        entry = self._resolve(server_key)
        url = entry["url"]
        headers = {"content-type": "application/json", "accept": "application/json"}
        headers.update(entry.get("headers") or {})  # OpenShell credential placeholders
        # Standard MCP tools/call over streamable_http (JSON-RPC 2.0). [confirm] the exact
        # streamable-http framing (SSE vs plain JSON) against the target MCP server.
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        import httpx

        async with httpx.AsyncClient(timeout=self._timeout) as http:
            resp = await http.post(url, json=payload, headers=headers)
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


def build_mcp_client(settings) -> Optional[McpClient]:
    """Worker-side MCP client selection: the registry client when the in-sandbox registry
    exists, else the stub (dev/CI). Returns None only if MCP should sim-fallback."""
    path = getattr(settings, "MCP_REGISTRY_PATH", None)
    if path and Path(path).exists():
        logger.info("MCP: using RegistryMcpClient over %s", path)
        return RegistryMcpClient(path)
    logger.info("MCP: registry %s absent — using StubMcpClient (dev/CI, no real list)", path)
    return StubMcpClient()
