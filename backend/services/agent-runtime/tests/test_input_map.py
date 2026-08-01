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


def test_mcp_arguments_omit_none_valued_fields():
    # ADR-052: a declared tool field with no resolved source is None → OMIT it (a closed inputSchema rejects a
    # null for a typed field → isError → MCP_TOOL_ERROR). Only fields with an actual value are sent.
    assert _mcp_arguments({"in": {"ticket_id": "T1", "request": None, "section_filter": None}}) == {"ticket_id": "T1"}
    assert _mcp_arguments({"a": None, "b": 2}) == {"b": 2}                # scalar None dropped
    assert _mcp_arguments({"in": {"x": 0, "y": False, "z": ""}}) == {"x": 0, "y": False, "z": ""}  # falsy≠None kept


def test_optional_composite_field_absent_is_omitted_then_included_on_loop_reentry():
    # ADR-052 e2e: Assess reads `resolution` from a loop-back producer (ObtainInfo). Per-field optionality means
    # the FIRST pass (info_resolution absent) resolves the composite with `resolution` omitted — no input_unresolved
    # — while its guaranteed siblings still resolve. On loop re-entry the produced artifact is included as normal.
    ctx = _ctx({"assess_input": {"fields": {
        "exception_id": {"from": "trigger", "path": "exception_id"},
        "resolution": {"from": "artifact", "name": "info_resolution", "path": "outcome", "optional": True},
    }}}, ["assess_input"])

    # first pass — info_resolution not produced yet: optional field → None → dropped from the tool arguments
    first = _gather_inputs(ctx, {"envelope": {"exception_id": "EXC-1"}, "artifacts": {}})
    assert first["assess_input"] == {"exception_id": "EXC-1", "resolution": None}
    assert _mcp_arguments(first) == {"exception_id": "EXC-1"}                 # resolution omitted, task runs

    # loop re-entry — info_resolution now present: the field resolves and is included
    reentry = _gather_inputs(ctx, {"envelope": {"exception_id": "EXC-1"},
                                   "artifacts": {"info_resolution": {"outcome": "repairable"}}})
    assert _mcp_arguments(reentry) == {"exception_id": "EXC-1", "resolution": "repairable"}


def test_non_optional_absent_artifact_field_still_raises():
    # The optionality is per-field: a NON-optional field whose source is absent is still a hard data-flow error.
    ctx = _ctx({"assess_input": {"fields": {
        "resolution": {"from": "artifact", "name": "info_resolution", "path": "outcome"},
    }}}, ["assess_input"])
    with pytest.raises(NodeExecutionError) as ei:
        _gather_inputs(ctx, {"envelope": {}, "artifacts": {}})
    assert "info_resolution" in str(ei.value)


def test_optional_top_level_artifact_input_absent_resolves_to_none():
    # A human read-only input from a branch/boundary producer is a TOP-LEVEL optional artifact source (not a
    # composite field): e.g. Task_ServeOrder reading `recovery`, produced only on the SLA-breach branch. On the
    # NORMAL path (the branch didn't run) it resolves to None — never "not produced upstream". Present → included.
    ctx = _ctx({"recovery": {"from": "artifact", "name": "recovery", "optional": True}}, ["recovery"])
    assert _gather_inputs(ctx, {"envelope": {}, "artifacts": {}})["recovery"] is None
    assert _gather_inputs(ctx, {"envelope": {}, "artifacts": {"recovery": {"note": "x"}}})["recovery"] == {"note": "x"}


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
