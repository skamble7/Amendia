# tests/test_scope_boundary_validation.py
"""ADR-041 — an interrupting timer boundary on a subProcess is safe only if the scope contains
autonomous read_only capabilities. A side-effectful task or a HITL gate inside the scope is refused.
"""
import hashlib

from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest

_VAL = {
    "artifact_key": "art.scope.val", "version": "1.0.0", "title": "v",
    "json_schema": {"$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "https://amendia.dev/schemas/artifacts/scope/val/1.0.0.json",
                    "type": "object", "additionalProperties": False, "required": ["ok"],
                    "properties": {"ok": {"type": "boolean"}}},
    "compatibility": "backward", "status": "active",
}


def _cap(cid, side_effect):
    return CapabilityDescriptor.model_validate({
        "descriptor_version": "1.0", "capability_id": cid, "version": "1.0.0", "title": cid,
        "kind": "skill", "side_effect": side_effect, "inputs": [],
        "outputs": [{"name": "out", "schema": "art.scope.val@^1.0.0"}],
        "runtime": {"kind": "skill", "entrypoint": "app.x:y"},
        "constraints": {"timeout_seconds": 30, "max_retries": 0}, "status": "active",
    })


def _bpmn(inner_task_xml: str) -> str:
    return ('<?xml version="1.0"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
            '<bpmn:process id="P" isExecutable="true">'
            '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
            '<bpmn:subProcess id="Sub"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>'
            '<bpmn:startEvent id="iS"><bpmn:outgoing>if1</bpmn:outgoing></bpmn:startEvent>'
            f'{inner_task_xml}'
            '<bpmn:endEvent id="iE"><bpmn:incoming>if2</bpmn:incoming></bpmn:endEvent>'
            '<bpmn:sequenceFlow id="if1" sourceRef="iS" targetRef="T"/>'
            '<bpmn:sequenceFlow id="if2" sourceRef="T" targetRef="iE"/>'
            '</bpmn:subProcess>'
            '<bpmn:boundaryEvent id="Sla" attachedToRef="Sub"><bpmn:timerEventDefinition>'
            '<bpmn:timeDuration>PT2H</bpmn:timeDuration></bpmn:timerEventDefinition></bpmn:boundaryEvent>'
            '<bpmn:endEvent id="End_Done"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
            '<bpmn:endEvent id="End_SLA"><bpmn:incoming>f_sla</bpmn:incoming></bpmn:endEvent>'
            '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Sub"/>'
            '<bpmn:sequenceFlow id="f2" sourceRef="Sub" targetRef="End_Done"/>'
            '<bpmn:sequenceFlow id="f_sla" sourceRef="Sla" targetRef="End_SLA"/>'
            '</bpmn:process></bpmn:definitions>')


def _manifest(binding: dict, bpmn: str, reqs) -> ProcessPackManifest:
    return ProcessPackManifest.model_validate({
        "manifest_version": "1.0", "pack_key": "scope-guard", "version": "1.0.0", "title": "g",
        "process": {"bpmn_file": "p.bpmn", "process_id": "P",
                    "bpmn_sha256": hashlib.sha256(bpmn.encode()).hexdigest()},
        "triage_rules": [{"rule_id": "r", "priority": 1,
                          "when": {"all": [{"field": "exception_type", "op": "eq", "value": "x"}]}}],
        "requires_capabilities": reqs, "artifacts": ["art.scope.val@^1.0.0"],
        "bindings": [binding], "status": "draft",
    })


async def _validate(cap_repo, schema_repo, caps, manifest, bpmn):
    from app.services.registration import register_schema
    from app.validation.pack_validator import PackValidator
    await register_schema(ArtifactSchemaRegistration.model_validate(_VAL), schema_repo)
    for c in caps:
        await cap_repo.insert(c)
    v = PackValidator(cap_repo, schema_repo, profile="common_executable")
    return await v.validate(manifest, bpmn)


async def test_side_effectful_task_in_timer_scope_refused(cap_repo, schema_repo):
    bpmn = _bpmn('<bpmn:serviceTask id="T"><bpmn:incoming>if1</bpmn:incoming><bpmn:outgoing>if2</bpmn:outgoing></bpmn:serviceTask>')
    binding = {"element_id": "T", "element_kind": "serviceTask",
               "executor": {"type": "capability", "capability": "cap.se.x@^1.0.0"},
               "hitl": {"mode": "approve_actions", "role": "role.ops"},
               "inputs": [], "outputs": [{"name": "out", "schema": "art.scope.val@^1.0.0"}]}
    report = await _validate(cap_repo, schema_repo, [_cap("cap.se.x", "side_effectful")],
                             _manifest(binding, bpmn, [{"ref": "cap.se.x@^1.0.0"}]), bpmn)
    assert "bpmn_subprocess_boundary_side_effect_unsupported" in set(report.error_codes())


async def test_hitl_gate_in_timer_scope_refused(cap_repo, schema_repo):
    bpmn = _bpmn('<bpmn:userTask id="T"><bpmn:incoming>if1</bpmn:incoming><bpmn:outgoing>if2</bpmn:outgoing></bpmn:userTask>')
    binding = {"element_id": "T", "element_kind": "userTask",
               "executor": {"type": "human", "role": "role.ops"},
               "hitl": {"mode": "manual", "role": "role.ops"},
               "inputs": [], "outputs": []}
    report = await _validate(cap_repo, schema_repo, [], _manifest(binding, bpmn, []), bpmn)
    assert "bpmn_subprocess_timer_scope_hitl_unsupported" in set(report.error_codes())
