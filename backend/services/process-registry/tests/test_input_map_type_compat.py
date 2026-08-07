# tests/test_input_map_type_compat.py
"""ADR-052 follow-up — Stage-5 rejects an input_map whose mapped SOURCE json-TYPE cannot satisfy the tool
field's DECLARED type (the wire "Screen"/"Notify" silent-hold class). A composite maps a trigger dotpath into a
declared tool field; an object→string or array<object>→array<string> mismatch is a commit-time hard reject
(``input_map_type_incompatible``); a type-compatible mapping passes; an opaque source degrades to no-op.
"""
import hashlib

from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest

_BPMN = ('<?xml version="1.0"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
         '<bpmn:process id="P" isExecutable="true">'
         '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
         '<bpmn:serviceTask id="A"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
         '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
         '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="A"/>'
         '<bpmn:sequenceFlow id="f2" sourceRef="A" targetRef="E"/>'
         '</bpmn:process></bpmn:definitions>')

# A wire-like trigger: creditor.account is a nested OBJECT; related_messages is an array of OBJECTS.
_TRIGGER = "art.x.trigger"
_TRIGGER_PROPS = {
    "exception_type": {"type": "string"},
    "payment": {"type": "object", "properties": {
        "creditor": {"type": "object", "properties": {
            "name": {"type": "string"},
            "account": {"type": "object", "properties": {"id": {"type": "string"}, "scheme": {"type": "string"}}},
        }},
        "creditor_flat": {"type": "object", "properties": {
            "name": {"type": "string"}, "account": {"type": "string"}}},
    }},
    "related_messages": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}}}},
}


def _schema(key, props):
    return {"artifact_key": key, "version": "1.0.0", "title": key,
            "json_schema": {"$schema": "https://json-schema.org/draft/2020-12/schema",
                            "$id": f"https://amendia.dev/schemas/artifacts/{key.split('.', 1)[1].replace('.', '/')}/1.0.0.json",
                            "type": "object", "additionalProperties": False, "properties": props},
            "compatibility": "backward", "status": "active"}


# screen-like tool input: `party` is a _typed_open object whose declared `account` is a STRING;
# `recipients` is an array<string>.
_IN_PROPS = {
    "party": {"type": "object", "properties": {
        "name": {"type": "string"}, "account": {"type": "string"}}},               # account: STRING (declared)
    "recipients": {"type": "array", "items": {"type": "string"}},                   # array<string>
    "envelope": {"type": "object"},                                                # open pass-through
}


def _mcp_cap(cid, in_key, out_key):
    return CapabilityDescriptor.model_validate({
        "descriptor_version": "1.0", "capability_id": cid, "version": "1.0.0", "title": cid,
        "kind": "mcp", "side_effect": "read_only",
        "inputs": [{"name": "a_in", "schema": f"{in_key}@^1.0.0"}],
        "outputs": [{"name": "a_out", "schema": f"{out_key}@^1.0.0"}],
        "runtime": {"kind": "mcp", "endpoint": "http://x/mcp", "tools": ["a"], "transport": "streamable_http"},
        "constraints": {"timeout_seconds": 30, "max_retries": 0}, "status": "active"})


def _manifest(input_map):
    binding = {"element_id": "A", "element_kind": "serviceTask",
               "executor": {"type": "capability", "capability": "cap.x.a@^1.0.0"}, "hitl": {"mode": "none"},
               "inputs": [{"name": "a_in", "schema": "art.x.a_in@^1.0.0"}],
               "outputs": [{"name": "a_out", "schema": "art.x.a_out@^1.0.0"}],
               "input_map": input_map}
    return ProcessPackManifest.model_validate({
        "manifest_version": "1.0", "pack_key": "imap-tc", "version": "1.0.0", "title": "t",
        "process": {"bpmn_file": "p.bpmn", "process_id": "P",
                    "bpmn_sha256": hashlib.sha256(_BPMN.encode()).hexdigest()},
        "trigger": f"{_TRIGGER}@^1.0.0",
        "triage_rules": [{"rule_id": "r", "priority": 1,
                          "when": {"all": [{"field": "exception_type", "op": "eq", "value": "x"}]}}],
        "requires_capabilities": [{"ref": "cap.x.a@^1.0.0"}],
        "artifacts": ["art.x.a_in@^1.0.0", "art.x.a_out@^1.0.0", f"{_TRIGGER}@^1.0.0"],
        "bindings": [binding], "status": "draft"})


async def _validate(cap_repo, schema_repo, input_map):
    from app.services.registration import register_schema
    from app.validation.pack_validator import PackValidator
    for reg in (_schema(_TRIGGER, _TRIGGER_PROPS), _schema("art.x.a_in", _IN_PROPS),
                _schema("art.x.a_out", {"v": {"type": "string"}})):
        await register_schema(ArtifactSchemaRegistration.model_validate(reg), schema_repo)
    await cap_repo.insert(_mcp_cap("cap.x.a", "art.x.a_in", "art.x.a_out"))
    v = PackValidator(cap_repo, schema_repo, profile="common_executable")
    return await v.validate(_manifest(input_map), _BPMN)


async def test_object_source_into_string_subfield_rejected(cap_repo, schema_repo):
    # party ← payment.creditor: creditor.account is OBJECT, tool party.account is STRING → the wire "Screen" hold.
    report = await _validate(cap_repo, schema_repo,
                             {"a_in": {"fields": {"party": {"from": "trigger", "path": "payment.creditor"}}}})
    assert "input_map_type_incompatible" in set(report.error_codes())
    assert not report.ok


async def test_array_of_object_into_array_of_string_rejected(cap_repo, schema_repo):
    # recipients ← related_messages: array<object> into array<string> → the wire "Notify" hold.
    report = await _validate(cap_repo, schema_repo,
                             {"a_in": {"fields": {"recipients": {"from": "trigger", "path": "related_messages"}}}})
    assert "input_map_type_incompatible" in set(report.error_codes())


async def test_type_compatible_composite_passes(cap_repo, schema_repo):
    # party ← payment.creditor_flat (account is a STRING) is type-compatible → no type error.
    report = await _validate(cap_repo, schema_repo,
                             {"a_in": {"fields": {"party": {"from": "trigger", "path": "payment.creditor_flat"}}}})
    assert "input_map_type_incompatible" not in set(report.error_codes())


async def test_open_target_field_tolerated(cap_repo, schema_repo):
    # envelope is an OPEN object → any source (even the whole creditor object) satisfies it → no type error.
    report = await _validate(cap_repo, schema_repo,
                             {"a_in": {"fields": {"envelope": {"from": "trigger", "path": "payment.creditor"}}}})
    assert "input_map_type_incompatible" not in set(report.error_codes())
