# tests/test_compensation_validation.py
"""ADR-043 — a compensable primary must be side-effectful (undoing a read-only step is meaningless), and
its ``isForCompensation`` handler must be a bound capability. A valid all-side-effectful pairing passes.
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


def _cap(cid, side_effect, *, outputs=None):
    return CapabilityDescriptor.model_validate({
        "descriptor_version": "1.0", "capability_id": cid, "version": "1.0.0", "title": cid,
        "kind": "skill", "side_effect": side_effect, "inputs": [],
        "outputs": outputs if outputs is not None else [{"name": "out", "schema": "art.scope.val@^1.0.0"}],
        "runtime": {"kind": "skill", "entrypoint": "app.x:y"},
        "constraints": {"timeout_seconds": 30, "max_retries": 0,
                        "min_hitl_mode": "approve_actions" if side_effect == "side_effectful" else "none"},
        "status": "active",
    })


# S → Release → End_Done, with an off-flow Reverse handler paired by a compensate boundary + association,
# and a compensate throw end event.
def _bpmn(primary_kind="serviceTask") -> str:
    return ('<?xml version="1.0"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
            '<bpmn:process id="P" isExecutable="true">'
            '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
            f'<bpmn:{primary_kind} id="Release"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:{primary_kind}>'
            '<bpmn:endEvent id="Throw"><bpmn:incoming>f2</bpmn:incoming><bpmn:compensateEventDefinition/></bpmn:endEvent>'
            '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Release"/>'
            '<bpmn:sequenceFlow id="f2" sourceRef="Release" targetRef="Throw"/>'
            '<bpmn:boundaryEvent id="Bnd" attachedToRef="Release"><bpmn:compensateEventDefinition/></bpmn:boundaryEvent>'
            '<bpmn:serviceTask id="Reverse" isForCompensation="true"></bpmn:serviceTask>'
            '<bpmn:association id="a" sourceRef="Bnd" targetRef="Reverse"/>'
            '</bpmn:process></bpmn:definitions>')


def _rel_binding(cap):
    return {"element_id": "Release", "element_kind": "serviceTask",
            "executor": {"type": "capability", "capability": f"{cap}@^1.0.0"},
            "hitl": {"mode": "approve_actions", "role": "role.ops"},
            "inputs": [], "outputs": [{"name": "out", "schema": "art.scope.val@^1.0.0"}]}


_REV_BINDING = {"element_id": "Reverse", "element_kind": "serviceTask",
                "executor": {"type": "capability", "capability": "cap.pay.undo@^1.0.0"},
                "hitl": {"mode": "approve_actions", "role": "role.ops"}, "inputs": [], "outputs": []}


def _manifest(bindings, bpmn, reqs) -> ProcessPackManifest:
    return ProcessPackManifest.model_validate({
        "manifest_version": "1.0", "pack_key": "comp-guard", "version": "1.0.0", "title": "g",
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


async def test_read_only_compensable_primary_refused(cap_repo, schema_repo):
    bpmn = _bpmn()
    report = await _validate(
        cap_repo, schema_repo, [_cap("cap.pay.ro", "read_only"), _cap("cap.pay.undo", "side_effectful", outputs=[])],
        _manifest([_rel_binding("cap.pay.ro"), _REV_BINDING], bpmn,
                  [{"ref": "cap.pay.ro@^1.0.0"}, {"ref": "cap.pay.undo@^1.0.0"}]), bpmn)
    assert "bpmn_compensation_handler_not_side_effect" in set(report.error_codes())


async def test_unbound_handler_refused(cap_repo, schema_repo):
    # the isForCompensation handler 'Reverse' has no binding at all
    bpmn = _bpmn()
    report = await _validate(
        cap_repo, schema_repo, [_cap("cap.pay.se", "side_effectful")],
        _manifest([_rel_binding("cap.pay.se")], bpmn, [{"ref": "cap.pay.se@^1.0.0"}]), bpmn)
    codes = set(report.error_codes())
    assert "bpmn_compensation_handler_unbound" in codes


async def test_valid_compensation_pairing_passes(cap_repo, schema_repo):
    bpmn = _bpmn()
    report = await _validate(
        cap_repo, schema_repo, [_cap("cap.pay.se", "side_effectful"), _cap("cap.pay.undo", "side_effectful", outputs=[])],
        _manifest([_rel_binding("cap.pay.se"), _REV_BINDING], bpmn,
                  [{"ref": "cap.pay.se@^1.0.0"}, {"ref": "cap.pay.undo@^1.0.0"}]), bpmn)
    codes = set(report.error_codes())
    assert "bpmn_compensation_handler_not_side_effect" not in codes
    assert "bpmn_compensation_handler_unbound" not in codes
