# tests/test_input_map.py
"""ADR-048 — capability input_map: resolve each input's data from the trigger / an upstream artifact /
a composite, so MCP-per-process packs (per-tool inputs that don't share names) actually chain. Domain-
neutral: field names come from the authored map, never the engine."""
import pytest

from app.engine.task_runner import (
    IOSpec, NodeContext, NodeExecutionError, _gather_inputs, _mcp_arguments,
)


def _ctx(input_map, input_names):
    return NodeContext(
        element_id="E", element_kind="serviceTask", hitl_mode="none", role=None,
        executor_type="capability",
        inputs=[IOSpec(name=n, schema_ref="art.x@^1.0.0") for n in input_names],
        input_map=input_map)


def test_resolve_trigger_artifact_and_composite():
    state = {"envelope": {"exception_id": "X", "reason_codes": ["AC01"]},
             "artifacts": {"enrich_output": {"score": 7}}}
    ctx = _ctx({"in": {"fields": {
        "eid": {"from": "trigger", "path": "exception_id"},
        "whole": {"from": "trigger"},
        "prior": {"from": "artifact", "name": "enrich_output", "path": "score"},
    }}}, ["in"])
    got = _gather_inputs(ctx, state)
    assert got["in"] == {"eid": "X", "whole": state["envelope"], "prior": 7}


def test_artifact_source_whole():
    state = {"envelope": {}, "artifacts": {"up": {"a": 1}}}
    got = _gather_inputs(_ctx({"in": {"from": "artifact", "name": "up"}}, ["in"]), state)
    assert got["in"] == {"a": 1}


def test_missing_upstream_artifact_is_execution_error_not_keyerror():
    ctx = _ctx({"in": {"from": "artifact", "name": "never_produced"}}, ["in"])
    with pytest.raises(NodeExecutionError) as ei:
        _gather_inputs(ctx, {"envelope": {}, "artifacts": {}})
    assert "never_produced" in str(ei.value) and "E" in str(ei.value)


def test_no_map_entry_reads_same_named_artifact_unchanged():
    # a binding without input_map behaves exactly as today (shared-name chaining).
    got = _gather_inputs(_ctx({}, ["a"]), {"envelope": {}, "artifacts": {"a": 42}})
    assert got["a"] == 42


def test_mcp_arguments_spread_composite_and_scalars():
    assert _mcp_arguments({"in": {"x": 1, "y": 2}}) == {"x": 1, "y": 2}   # composite → the tool args
    assert _mcp_arguments({"a": 1, "b": 2}) == {"a": 1, "b": 2}           # scalars key by name


def test_field_level_map_resolves_then_spreads_into_tool_arguments():
    # ADR-048 D4: a field-level composite input (dossier←upstream output, exception_id/reason_codes←trigger)
    # resolves to the object the tool expects, then spreads into the MCP tool-call arguments as-is.
    state = {"envelope": {"exception_id": "EXC-1", "reason_codes": ["AC01"]},
             "artifacts": {"enrich_output": {"dossier": {"beneficiary": "Aurora"}, "score": 7}}}
    ctx = _ctx({"assess_input": {"fields": {
        "dossier": {"from": "artifact", "name": "enrich_output", "path": "dossier"},
        "exception_id": {"from": "trigger", "path": "exception_id"},
        "reason_codes": {"from": "trigger", "path": "reason_codes"},
    }}}, ["assess_input"])
    inputs = _gather_inputs(ctx, state)
    assert _mcp_arguments(inputs) == {
        "dossier": {"beneficiary": "Aurora"}, "exception_id": "EXC-1", "reason_codes": ["AC01"]}
