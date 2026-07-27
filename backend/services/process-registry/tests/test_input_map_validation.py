# tests/test_input_map_validation.py
"""ADR-048 — the seed-state contract. Stage-5 validates the REAL data-flow: an input is satisfied by a
same-named upstream output, or by an input_map (trigger / a produced upstream artifact). An input that is
neither mapped nor produced is an ERROR (it would hard-fail at runtime) — so an MCP-per-process pack
(per-tool inputs, no map) fails validation instead of activating and dying at step 1.
"""
import hashlib

from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest


def _schema(key):
    return {"artifact_key": key, "version": "1.0.0", "title": key,
            "json_schema": {"$schema": "https://json-schema.org/draft/2020-12/schema",
                            "$id": f"https://amendia.dev/schemas/artifacts/{key.split('.', 1)[1].replace('.', '/')}/1.0.0.json",
                            "type": "object", "additionalProperties": False,
                            "required": ["v"], "properties": {"v": {"type": "string"}}},
            "compatibility": "backward", "status": "active"}


def _cap(cid, in_name, in_key, out_name, out_key):
    return CapabilityDescriptor.model_validate({
        "descriptor_version": "1.0", "capability_id": cid, "version": "1.0.0", "title": cid,
        "kind": "skill", "side_effect": "read_only",
        "inputs": [{"name": in_name, "schema": f"{in_key}@^1.0.0"}],
        "outputs": [{"name": out_name, "schema": f"{out_key}@^1.0.0"}],
        "runtime": {"kind": "skill", "entrypoint": "app.x:y"},
        "constraints": {"timeout_seconds": 30, "max_retries": 0}, "status": "active"})


# start → A → B → end
_BPMN = ('<?xml version="1.0"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
         '<bpmn:process id="P" isExecutable="true">'
         '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
         '<bpmn:serviceTask id="A"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
         '<bpmn:serviceTask id="B"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:serviceTask>'
         '<bpmn:endEvent id="E"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>'
         '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="A"/>'
         '<bpmn:sequenceFlow id="f2" sourceRef="A" targetRef="B"/>'
         '<bpmn:sequenceFlow id="f3" sourceRef="B" targetRef="E"/>'
         '</bpmn:process></bpmn:definitions>')


def _binding(elem, cap, in_name, in_key, out_name, out_key, input_map=None):
    b = {"element_id": elem, "element_kind": "serviceTask",
         "executor": {"type": "capability", "capability": f"{cap}@^1.0.0"}, "hitl": {"mode": "none"},
         "inputs": [{"name": in_name, "schema": f"{in_key}@^1.0.0"}],
         "outputs": [{"name": out_name, "schema": f"{out_key}@^1.0.0"}]}
    if input_map is not None:
        b["input_map"] = input_map
    return b


def _manifest(bindings):
    return ProcessPackManifest.model_validate({
        "manifest_version": "1.0", "pack_key": "imap", "version": "1.0.0", "title": "t",
        "process": {"bpmn_file": "p.bpmn", "process_id": "P",
                    "bpmn_sha256": hashlib.sha256(_BPMN.encode()).hexdigest()},
        "triage_rules": [{"rule_id": "r", "priority": 1,
                          "when": {"all": [{"field": "exception_type", "op": "eq", "value": "x"}]}}],
        "requires_capabilities": [{"ref": "cap.x.a@^1.0.0"}, {"ref": "cap.x.b@^1.0.0"}],
        "artifacts": ["art.x.a_in@^1.0.0", "art.x.a_out@^1.0.0", "art.x.b_in@^1.0.0", "art.x.b_out@^1.0.0"],
        "bindings": bindings, "status": "draft"})


async def _validate(cap_repo, schema_repo, bindings):
    from app.services.registration import register_schema
    from app.validation.pack_validator import PackValidator
    for k in ("art.x.a_in", "art.x.a_out", "art.x.b_in", "art.x.b_out"):
        await register_schema(ArtifactSchemaRegistration.model_validate(_schema(k)), schema_repo)
    await cap_repo.insert(_cap("cap.x.a", "a_in", "art.x.a_in", "a_out", "art.x.a_out"))
    await cap_repo.insert(_cap("cap.x.b", "b_in", "art.x.b_in", "b_out", "art.x.b_out"))
    v = PackValidator(cap_repo, schema_repo, profile="common_executable")
    return await v.validate(_manifest(bindings), _BPMN)


def test_input_map_contract_round_trip():
    # ADR-048: the Binding.input_map (trigger / artifact / composite fields) round-trips by-alias, and a
    # binding without it defaults to {} (behaves as today).
    from amendia_contracts.process_pack import Binding
    doc = {"element_id": "E", "element_kind": "serviceTask",
           "executor": {"type": "capability", "capability": "cap.x.y@^1.0.0"}, "hitl": {"mode": "none"},
           "inputs": [{"name": "in", "schema": "art.x.in@^1.0.0"}],
           "input_map": {"in": {"fields": {
               "eid": {"from": "trigger", "path": "exception_id"},
               "whole": {"from": "trigger"},
               "prior": {"from": "artifact", "name": "up_out", "path": "score"}}}}}
    b = Binding.model_validate(doc)
    round = b.model_dump(by_alias=True, mode="json", exclude_defaults=True)
    assert round["input_map"] == doc["input_map"]
    assert Binding.model_validate({"element_id": "E", "element_kind": "serviceTask",
                                   "executor": {"type": "capability", "capability": "cap.x.y@^1.0.0"},
                                   "hitl": {"mode": "none"}}).input_map == {}


async def test_unmapped_unproduced_input_is_error(cap_repo, schema_repo):
    # ws-stan shape: per-tool inputs, NO input_map → both inputs are unproduced → hard errors (was a warning).
    report = await _validate(cap_repo, schema_repo, [
        _binding("A", "cap.x.a", "a_in", "art.x.a_in", "a_out", "art.x.a_out"),
        _binding("B", "cap.x.b", "b_in", "art.x.b_in", "b_out", "art.x.b_out")])
    codes = set(report.error_codes())
    assert "unproduced_input" in codes
    assert not report.ok


async def test_input_map_trigger_and_upstream_artifact_valid(cap_repo, schema_repo):
    # A reads the trigger; B reads A's output by name → clean.
    report = await _validate(cap_repo, schema_repo, [
        _binding("A", "cap.x.a", "a_in", "art.x.a_in", "a_out", "art.x.a_out",
                 input_map={"a_in": {"from": "trigger"}}),
        _binding("B", "cap.x.b", "b_in", "art.x.b_in", "b_out", "art.x.b_out",
                 input_map={"b_in": {"from": "artifact", "name": "a_out"}})])
    assert "unproduced_input" not in set(report.error_codes())
    assert "binding_input_unproduced" not in set(report.error_codes())


async def test_input_map_referencing_unproduced_artifact_is_error(cap_repo, schema_repo):
    report = await _validate(cap_repo, schema_repo, [
        _binding("A", "cap.x.a", "a_in", "art.x.a_in", "a_out", "art.x.a_out",
                 input_map={"a_in": {"from": "trigger"}}),
        _binding("B", "cap.x.b", "b_in", "art.x.b_in", "b_out", "art.x.b_out",
                 input_map={"b_in": {"from": "artifact", "name": "does_not_exist"}})])
    errs = [f for f in report.findings if f.code == "binding_input_unproduced"]
    assert errs and any(f.element_id == "B" for f in errs)
