# tests/_mcp_server_tools.py
"""ADR-047 D2 — the wire-transfer MCP server's tool library, as an in-process tool map for tests.

The re-homed seed packs are MCP-backed: their `mcp` capabilities dispatch `tools/call` to the
`wire_transfer_exception` server. To run them in the non-e2e suite, the harness wires an
``InProcessMcpClient`` to the server's *own* pure tool handlers — the single source of truth (the same code
the deployed server runs), imported here without the mcp SDK (handlers.py is SDK-free). No tool logic is
duplicated in the platform or the tests.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Dict

# handlers.py is a pure module (stdlib only) — importable via sys.path with no packaging coupling.
_SERVER_SRC = Path(__file__).resolve().parents[4] / "mcp_stub" / "servers" / "wire_transfer_exception" / "src"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

from wire_transfer_exception_mcp.handlers import TOOLS_BY_NAME  # noqa: E402


def server_tool_map() -> Dict[str, Callable[[dict], dict]]:
    """tool name → handler(arguments) → structured result — the map an InProcessMcpClient dispatches to."""
    return {name: spec["handler"] for name, spec in TOOLS_BY_NAME.items()}
