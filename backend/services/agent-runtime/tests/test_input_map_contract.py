# tests/test_input_map_contract.py
"""ADR-048 / ADR-047 D2 — a binding input_map must send ONLY fields the tool's inputSchema declares.

The MCP server CLOSES every tool inputSchema (``additionalProperties: false``, enforced by the server's own
``check_compliance``) and 400-rejects a call carrying an undeclared argument. A binding's ``input_map``
composite is spread into the tool's arguments (``_mcp_arguments``), so every composite field must be a declared
input — else the tool fails on the DEPLOYED path while the in-process test double (which dispatches straight to
the handler, no schema validation) stays green. That exact divergence sent AC01 into the ObtainInfo loop: the
assess composite carried an undeclared ``envelope`` and the real server rejected the call.

This is the fast structural guard; `test_http_mcp_client_integration` exercises the same coupling over the wire.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SERVER_SRC = Path(__file__).resolve().parents[4] / "mcp_stub" / "servers" / "wire_transfer_exception" / "src"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))
from wire_transfer_exception_mcp.handlers import TOOLS_BY_NAME  # noqa: E402

_SEED_ROOT = Path(__file__).resolve().parents[1] / "seed"
_PACKS = sorted((p.parent for p in _SEED_ROOT.glob("*/manifest.json")), key=lambda p: p.name)


def _composite_fields(input_map: dict):
    """The argument keys a binding's input_map spreads into the tool call (``_mcp_arguments`` semantics)."""
    fields = set()
    for name, src in (input_map or {}).items():
        if isinstance(src, dict) and "fields" in src:
            fields |= set(src["fields"].keys())
        else:
            fields.add(name)
    return fields


@pytest.mark.parametrize("pack_dir", _PACKS, ids=lambda p: p.name)
def test_mcp_input_map_fields_are_declared_in_the_tool_schema(pack_dir: Path):
    manifest = json.loads((pack_dir / "manifest.json").read_text())
    caps = {}
    for f in (pack_dir / "capabilities").glob("*.json"):
        d = json.loads(f.read_text())
        caps[d["capability_id"]] = d

    violations = []
    for b in manifest["bindings"]:
        ex = b.get("executor", {})
        ref = ex.get("capability") if ex.get("type") == "capability" else ex.get("assist_capability")
        if not ref:
            continue
        cap = caps.get(ref.split("@", 1)[0])
        if not cap or cap.get("kind") != "mcp":
            continue
        tool = (cap["runtime"].get("tools") or [None])[0]
        schema = TOOLS_BY_NAME.get(tool, {}).get("input_schema", {})
        if schema.get("additionalProperties") is not False:
            continue  # an open schema tolerates extras — nothing to reconcile
        declared = set(schema.get("properties", {}).keys())
        sent = _composite_fields(b.get("input_map") or {})
        undeclared = sent - declared
        if undeclared:
            violations.append(
                f"{b['element_id']} (tool '{tool}'): input_map sends {sorted(undeclared)} "
                f"not in the closed inputSchema {sorted(declared)}")

    assert not violations, (
        "input_map sends arguments the MCP server will 400-reject (undeclared in the closed inputSchema):\n"
        + "\n".join(violations))
