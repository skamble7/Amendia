# tests/test_mcp_arguments_fallback.py
"""ADR-052: the MCP argument object comes from the authored input_map (`ctx.extras["mcp_arguments"]`) and is
used AS-IS — even when it resolves to `{}`. Only a MISSING map (None — set by task_runner when the binding has
no input_map) falls back to the legacy `{envelope, inputs}` wrapper. Distinguishing None from `{}` matters: the
old `mcp_args or {...}` selected the wrapper for an empty authored map, which a closed tool inputSchema rejects
(isError "Additional properties are not allowed ('envelope','inputs')")."""
import pytest

from amendia_contracts.capability import CapabilityDescriptor

from app.engine.executor.base import ExecutionContext
from app.engine.executor.core import _execute_mcp_real

_DESC = CapabilityDescriptor.model_validate({
    "descriptor_version": "1.0", "capability_id": "cap.x.a", "version": "1.0.0", "title": "a",
    "kind": "mcp", "side_effect": "read_only",
    "inputs": [{"name": "a_in", "schema": "art.x.a_in@^1.0.0"}],
    "outputs": [{"name": "a_out", "schema": "art.x.a_out@^1.0.0"}],
    "runtime": {"kind": "mcp", "endpoint": "http://x/mcp", "tools": ["a"], "transport": "streamable_http"},
    "constraints": {"timeout_seconds": 30, "max_retries": 0}, "status": "active"})


class _FakeClient:
    def __init__(self):
        self.captured = None

    async def call_tool(self, *, endpoint, tool, arguments, transport, headers):
        self.captured = arguments
        return {"ok": True}


def _run(extras, inputs):
    fake = _FakeClient()
    ctx = ExecutionContext(envelope={"exception_id": "X"}, mode="execute", simulation=False, extras=extras)
    _execute_mcp_real(_DESC, inputs, ctx, fake)
    return fake.captured


def test_authored_empty_map_calls_tool_with_empty_args_not_the_wrapper():
    # an authored input_map that resolves to {} → call the tool with {} exactly, never {envelope, inputs}.
    captured = _run({"mcp_arguments": {}, "output_schemas": {}, "element_id": "El"}, {"a_in": {}})
    assert captured == {}


def test_authored_nonempty_map_passes_the_resolved_args_as_is():
    captured = _run({"mcp_arguments": {"ticket_id": "TKT-1"}, "output_schemas": {}, "element_id": "El"},
                    {"a_in": {"ticket_id": "TKT-1"}})
    assert captured == {"ticket_id": "TKT-1"}


def test_no_map_falls_back_to_the_legacy_envelope_inputs_wrapper():
    # no `mcp_arguments` key (None) → seed-pack path: the legacy wrapper, unchanged.
    captured = _run({"output_schemas": {}, "element_id": "El"}, {"a_in": {"a": 1}})
    assert captured == {"envelope": {"exception_id": "X"}, "inputs": {"a_in": {"a": 1}}}
