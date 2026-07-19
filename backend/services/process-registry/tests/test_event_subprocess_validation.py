# tests/test_event_subprocess_validation.py
"""ADR-042 — a process-level interrupting **timer** event sub-process makes the WHOLE process a timer
scope. Like a subProcess timer boundary (ADR-041), that scope is safe only if every task in it is an
autonomous read_only capability; a side-effectful task or a HITL gate in the process scope is refused
(the ESP body — the handler — is excluded). A valid all-read_only process scope passes.
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


def _bpmn(main_task_xml: str) -> str:
    """S → T → End_Done, plus a PROCESS-LEVEL timer event sub-process eS(timer) → H → eEnd."""
    return ('<?xml version="1.0"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
            '<bpmn:process id="P" isExecutable="true">'
            '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
            f'{main_task_xml}'
            '<bpmn:endEvent id="End_Done"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
            '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="T"/>'
            '<bpmn:sequenceFlow id="f2" sourceRef="T" targetRef="End_Done"/>'
            '<bpmn:subProcess id="ESP" triggeredByEvent="true">'
            '<bpmn:startEvent id="eS"><bpmn:timerEventDefinition><bpmn:timeDuration>PT2H</bpmn:timeDuration>'
            '</bpmn:timerEventDefinition><bpmn:outgoing>ef1</bpmn:outgoing></bpmn:startEvent>'
            '<bpmn:serviceTask id="H"><bpmn:incoming>ef1</bpmn:incoming><bpmn:outgoing>ef2</bpmn:outgoing></bpmn:serviceTask>'
            '<bpmn:endEvent id="eEnd"><bpmn:incoming>ef2</bpmn:incoming></bpmn:endEvent>'
            '<bpmn:sequenceFlow id="ef1" sourceRef="eS" targetRef="H"/>'
            '<bpmn:sequenceFlow id="ef2" sourceRef="H" targetRef="eEnd"/>'
            '</bpmn:subProcess>'
            '</bpmn:process></bpmn:definitions>')


_HANDLE_BINDING = {"element_id": "H", "element_kind": "serviceTask",
                   "executor": {"type": "capability", "capability": "cap.ro.h@^1.0.0"},
                   "hitl": {"mode": "none"},
                   "inputs": [], "outputs": [{"name": "out", "schema": "art.scope.val@^1.0.0"}]}


def _manifest(bindings: list, bpmn: str, reqs) -> ProcessPackManifest:
    return ProcessPackManifest.model_validate({
        "manifest_version": "1.0", "pack_key": "esp-guard", "version": "1.0.0", "title": "g",
        "process": {"bpmn_file": "p.bpmn", "process_id": "P",
                    "bpmn_sha256": hashlib.sha256(bpmn.encode()).hexdigest()},
        "triage_rules": [{"rule_id": "r", "priority": 1,
                          "when": {"all": [{"field": "exception_type", "op": "eq", "value": "x"}]}}],
        "requires_capabilities": reqs, "artifacts": ["art.scope.val@^1.0.0"],
        "bindings": bindings, "status": "draft",
    })


async def _validate(cap_repo, schema_repo, caps, manifest, bpmn):
    from app.services.registration import register_schema
    from app.validation.pack_validator import PackValidator
    await register_schema(ArtifactSchemaRegistration.model_validate(_VAL), schema_repo)
    for c in caps:
        await cap_repo.insert(c)
    v = PackValidator(cap_repo, schema_repo, profile="common_executable")
    return await v.validate(manifest, bpmn)


async def test_side_effectful_task_in_process_timer_scope_refused(cap_repo, schema_repo):
    bpmn = _bpmn('<bpmn:serviceTask id="T"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>')
    t_binding = {"element_id": "T", "element_kind": "serviceTask",
                 "executor": {"type": "capability", "capability": "cap.se.x@^1.0.0"},
                 "hitl": {"mode": "none"},
                 "inputs": [], "outputs": [{"name": "out", "schema": "art.scope.val@^1.0.0"}]}
    report = await _validate(
        cap_repo, schema_repo, [_cap("cap.se.x", "side_effectful"), _cap("cap.ro.h", "read_only")],
        _manifest([t_binding, _HANDLE_BINDING], bpmn,
                  [{"ref": "cap.se.x@^1.0.0"}, {"ref": "cap.ro.h@^1.0.0"}]), bpmn)
    assert "bpmn_subprocess_boundary_side_effect_unsupported" in set(report.error_codes())


async def test_hitl_gate_in_process_timer_scope_refused(cap_repo, schema_repo):
    bpmn = _bpmn('<bpmn:userTask id="T"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:userTask>')
    t_binding = {"element_id": "T", "element_kind": "userTask",
                 "executor": {"type": "human", "role": "role.ops"},
                 "hitl": {"mode": "manual", "role": "role.ops"}, "inputs": [], "outputs": []}
    report = await _validate(cap_repo, schema_repo, [_cap("cap.ro.h", "read_only")],
                             _manifest([t_binding, _HANDLE_BINDING], bpmn, [{"ref": "cap.ro.h@^1.0.0"}]), bpmn)
    assert "bpmn_subprocess_timer_scope_hitl_unsupported" in set(report.error_codes())


async def test_all_read_only_process_timer_scope_passes(cap_repo, schema_repo):
    bpmn = _bpmn('<bpmn:serviceTask id="T"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>')
    t_binding = {"element_id": "T", "element_kind": "serviceTask",
                 "executor": {"type": "capability", "capability": "cap.ro.t@^1.0.0"},
                 "hitl": {"mode": "none"},
                 "inputs": [], "outputs": [{"name": "out", "schema": "art.scope.val@^1.0.0"}]}
    report = await _validate(
        cap_repo, schema_repo, [_cap("cap.ro.t", "read_only"), _cap("cap.ro.h", "read_only")],
        _manifest([t_binding, _HANDLE_BINDING], bpmn,
                  [{"ref": "cap.ro.t@^1.0.0"}, {"ref": "cap.ro.h@^1.0.0"}]), bpmn)
    codes = set(report.error_codes())
    assert "bpmn_subprocess_boundary_side_effect_unsupported" not in codes
    assert "bpmn_subprocess_timer_scope_hitl_unsupported" not in codes
    assert "bpmn_event_subprocess_unsupported" not in codes
