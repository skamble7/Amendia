# tests/test_input_map_overflow.py
"""ADR-052 Part A — Stage-5 rejects an input_map that OVERFLOWS a closed MCP tool inputSchema. At runtime
(task_runner._mcp_arguments) a WHOLE object source ({"from":"trigger"}) spreads every field of that object into
the tool call args; if those keys aren't declared on the tool's closed input schema the SDK rejects the call
(isError → MCP_TOOL_ERROR) and the capability produces nothing. The pack activates with 0 errors, so the check
here is what catches it. A per-field composite limited to declared fields passes; an OPEN input tolerates extras.
"""
import hashlib

from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest

# start → A → end
_BPMN = ('<?xml version="1.0"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
         '<bpmn:process id="P" isExecutable="true">'
         '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
         '<bpmn:serviceTask id="A"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
         '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
         '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="A"/>'
         '<bpmn:sequenceFlow id="f2" sourceRef="A" targetRef="E"/>'
         '</bpmn:process></bpmn:definitions>')

_TRIGGER = "art.x.order"           # the declared trigger: MORE fields than the tool accepts
_TRIGGER_PROPS = {"ticket_id": {"type": "string"}, "order_type": {"type": "string"}, "table": {"type": "string"}}


def _schema(key, props, *, closed=True):
    js = {"$schema": "https://json-schema.org/draft/2020-12/schema",
          "$id": f"https://amendia.dev/schemas/artifacts/{key.split('.', 1)[1].replace('.', '/')}/1.0.0.json",
          "type": "object", "properties": props}
    if closed:
        js["additionalProperties"] = False
    return {"pack_key": "imap-of", "pack_version": "1.0.0",
            "artifact_key": key, "version": "1.0.0", "title": key, "json_schema": js,
            "compatibility": "backward", "status": "active"}


def _mcp_cap(cid, in_key, out_key):
    return CapabilityDescriptor.model_validate({
        "descriptor_version": "1.0", "pack_key": "imap-of", "pack_version": "1.0.0",
        "capability_id": cid, "version": "1.0.0", "title": cid,
        "kind": "mcp", "side_effect": "read_only",
        "inputs": [{"name": "a_in", "schema": f"{in_key}@^1.0.0"}],
        "outputs": [{"name": "a_out", "schema": f"{out_key}@^1.0.0"}],
        "runtime": {"kind": "mcp", "endpoint": "http://x/mcp", "tools": ["a"], "transport": "streamable_http"},
        "constraints": {"timeout_seconds": 30, "max_retries": 0}, "status": "active"})


def _manifest(in_key, input_map):
    binding = {"element_id": "A", "element_kind": "serviceTask",
               "executor": {"type": "capability", "capability": "cap.x.a@^1.0.0"}, "hitl": {"mode": "none"},
               "inputs": [{"name": "a_in", "schema": f"{in_key}@^1.0.0"}],
               "outputs": [{"name": "a_out", "schema": "art.x.a_out@^1.0.0"}],
               "input_map": input_map}
    return ProcessPackManifest.model_validate({
        "manifest_version": "1.0", "pack_key": "imap-of", "version": "1.0.0", "title": "t",
        "process": {"bpmn_file": "p.bpmn", "process_id": "P",
                    "bpmn_sha256": hashlib.sha256(_BPMN.encode()).hexdigest()},
        "trigger": f"{_TRIGGER}@^1.0.0",
        "triage_rules": [{"rule_id": "r", "priority": 1,
                          "when": {"all": [{"field": "order_type", "op": "eq", "value": "x"}]}}],
        "requires_capabilities": [{"ref": "cap.x.a@^1.0.0"}],
        "artifacts": [f"{in_key}@^1.0.0", "art.x.a_out@^1.0.0", f"{_TRIGGER}@^1.0.0"],
        "bindings": [binding], "status": "draft"})


async def _validate(cap_repo, schema_repo, *, in_key, in_props, input_map, in_closed=True):
    from app.services.registration import register_schema
    from app.validation.pack_validator import PackValidator
    for reg in (_schema(_TRIGGER, _TRIGGER_PROPS),
                _schema(in_key, in_props, closed=in_closed),
                _schema("art.x.a_out", {"v": {"type": "string"}})):
        await register_schema(ArtifactSchemaRegistration.model_validate(reg), schema_repo)
    await cap_repo.insert(_mcp_cap("cap.x.a", in_key, "art.x.a_out"))
    v = PackValidator(cap_repo, schema_repo, profile="common_executable")
    return await v.validate(_manifest(in_key, input_map), _BPMN)


async def test_whole_trigger_into_closed_tool_schema_overflows(cap_repo, schema_repo):
    # the buggy auto-fill shape: a WHOLE-trigger source into a closed tool whose input has only {ticket_id}.
    report = await _validate(cap_repo, schema_repo, in_key="art.x.a_in",
                             in_props={"ticket_id": {"type": "string"}},
                             input_map={"a_in": {"from": "trigger"}})
    assert "input_map_overflows_tool_schema" in set(report.error_codes())
    assert not report.ok


async def test_per_field_map_limited_to_declared_fields_passes(cap_repo, schema_repo):
    # the ADR-052 auto-fill shape: a per-field composite over the declared input field only.
    report = await _validate(cap_repo, schema_repo, in_key="art.x.a_in",
                             in_props={"ticket_id": {"type": "string"}},
                             input_map={"a_in": {"fields": {"ticket_id": {"from": "trigger", "path": "ticket_id"}}}})
    assert "input_map_overflows_tool_schema" not in set(report.error_codes())


async def test_open_tool_schema_with_whole_trigger_is_tolerated(cap_repo, schema_repo):
    # an OPEN input schema tolerates extra args → no overflow error even for a whole-trigger source.
    report = await _validate(cap_repo, schema_repo, in_key="art.x.a_in_open",
                             in_props={"ticket_id": {"type": "string"}}, in_closed=False,
                             input_map={"a_in": {"from": "trigger"}})
    assert "input_map_overflows_tool_schema" not in set(report.error_codes())
