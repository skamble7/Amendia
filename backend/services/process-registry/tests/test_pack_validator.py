# tests/test_pack_validator.py
import copy
import json

import pytest

from amendia_contracts.process_pack import ProcessPackManifest
from tests.conftest import SEED, load_bpmn, load_sample


def manifest_dict() -> dict:
    return json.loads((SEED / "manifest.json").read_text())


def build(d: dict) -> ProcessPackManifest:
    return ProcessPackManifest.model_validate(d)


async def _validate(validator, manifest, bpmn=None):
    return await validator.validate(manifest, bpmn if bpmn is not None else load_bpmn(),
                                    sample_envelopes=[load_sample()])


def _errs(report):
    return set(report.error_codes())


async def test_activation_gate_rejects_parallel_gateway(registered, validator):
    # ADR-027 §1a: attach may accept a parallel gateway (documented), but validate/activate must
    # refuse it — the same structural gate the runtime compiler raises off.
    d = manifest_dict()
    pid = d["process"]["process_id"]
    parallel = (
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
        f'<bpmn:process id="{pid}" isExecutable="true">'
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:parallelGateway id="GW"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>fa</bpmn:outgoing><bpmn:outgoing>fb</bpmn:outgoing></bpmn:parallelGateway>'
        '<bpmn:endEvent id="ea"><bpmn:incoming>fa</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:endEvent id="eb"><bpmn:incoming>fb</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="GW"/>'
        '<bpmn:sequenceFlow id="fa" sourceRef="GW" targetRef="ea"/>'
        '<bpmn:sequenceFlow id="fb" sourceRef="GW" targetRef="eb"/>'
        '</bpmn:process></bpmn:definitions>'
    )
    report = await _validate(validator, build(d), bpmn=parallel)
    assert not report.ok
    assert "bpmn_parallel_gateway_unsupported" in _errs(report)


async def test_parallel_profile_allows_parallel_gateway(registered, cap_repo, schema_repo):
    # ADR-027 Phase 2.1/2.5: under the "parallel" profile the activation gate no longer refuses a
    # WELL-FORMED fork/join (the runtime compiler runs it under the matching profile). Fork/join
    # structural validation (2.5.d) still applies — this diagram is balanced and block-structured.
    from app.validation.pack_validator import PackValidator

    v = PackValidator(cap_repo, schema_repo, profile="parallel")
    d = manifest_dict()
    pid = d["process"]["process_id"]
    parallel = (
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
        f'<bpmn:process id="{pid}" isExecutable="true">'
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:parallelGateway id="Fork"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>fa</bpmn:outgoing><bpmn:outgoing>fb</bpmn:outgoing></bpmn:parallelGateway>'
        '<bpmn:serviceTask id="A"><bpmn:incoming>fa</bpmn:incoming><bpmn:outgoing>aj</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:serviceTask id="B"><bpmn:incoming>fb</bpmn:incoming><bpmn:outgoing>bj</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:parallelGateway id="Join"><bpmn:incoming>aj</bpmn:incoming><bpmn:incoming>bj</bpmn:incoming><bpmn:outgoing>je</bpmn:outgoing></bpmn:parallelGateway>'
        '<bpmn:endEvent id="E"><bpmn:incoming>je</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Fork"/>'
        '<bpmn:sequenceFlow id="fa" sourceRef="Fork" targetRef="A"/>'
        '<bpmn:sequenceFlow id="fb" sourceRef="Fork" targetRef="B"/>'
        '<bpmn:sequenceFlow id="aj" sourceRef="A" targetRef="Join"/>'
        '<bpmn:sequenceFlow id="bj" sourceRef="B" targetRef="Join"/>'
        '<bpmn:sequenceFlow id="je" sourceRef="Join" targetRef="E"/>'
        '</bpmn:process></bpmn:definitions>'
    )
    report = await _validate(v, build(d), bpmn=parallel)
    assert "bpmn_parallel_gateway_unsupported" not in _errs(report)
    assert "bpmn_parallel_unbalanced" not in _errs(report)
    assert "bpmn_parallel_nested_unsupported" not in _errs(report)
    assert "bpmn_parallel_unstructured" not in _errs(report)


async def test_golden_path_passes(registered, validator):
    report = await _validate(validator, build(manifest_dict()))
    assert report.ok, report.error_codes()
    # the smoke test recorded an info finding that the wire rule matches the sample
    assert any(f.code == "triage_rule_smoke" and "MATCH" in f.message for f in report.findings)


async def test_unbound_task(registered, validator):
    d = manifest_dict()
    d["bindings"] = [b for b in d["bindings"] if b["element_id"] != "Task_NotifyParties"]
    report = await _validate(validator, build(d))
    assert "unbound_task" in _errs(report)


async def test_unknown_capability(registered, validator):
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_EnrichPayment":
            b["executor"]["capability"] = "cap.payment.does_not_exist@^1.0.0"
    report = await _validate(validator, build(d))
    assert "unknown_capability" in _errs(report)


async def test_only_deprecated_versions_in_range(registered, validator, cap_repo):
    await cap_repo.set_status("cap.payment.sanctions_screen", "1.0.0", "deprecated")
    report = await _validate(validator, build(manifest_dict()))
    assert "capability_only_deprecated" in _errs(report)


async def test_side_effectful_at_review_after(registered, validator):
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_ApplyRepair":
            b["hitl"] = {"mode": "review_after", "role": "role.payments.ops_approver"}
    report = await _validate(validator, build(d))
    assert "side_effect_requires_approve_actions" in _errs(report)


async def test_binding_io_name_mismatch(registered, validator):
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_AssessRepairability":
            b["outputs"] = [{"name": "wrong_name", "schema": "art.payment.repair_verdict@^1.0.0"}]
    report = await _validate(validator, build(d))
    assert "binding_io_mismatch" in _errs(report)


async def test_gateway_variable_on_non_required_field(registered, validator):
    d = manifest_dict()
    d["gateway_variables"][0]["variable"] = "beneficiary.proposed_correction"
    report = await _validate(validator, build(d))
    assert "gateway_variable_not_required" in _errs(report)


async def test_sod_ghost_element(registered, validator):
    d = manifest_dict()
    d["policies"]["separation_of_duties"].append(
        {"constraint": "distinct_actor", "elements": ["Task_DraftRepair", "Task_Ghost"]}
    )
    report = await _validate(validator, build(d))
    assert "sod_unknown_element" in _errs(report)


async def test_no_bpmn_skips_stages(registered, validator):
    report = await validator.validate(build(manifest_dict()), None, sample_envelopes=[])
    codes = _errs(report)
    assert "bpmn_missing" in codes
    assert "stage_skipped" in codes  # stages 2/5/6 skipped


def _with_message_catch(bpmn: str) -> str:
    """Insert a message intermediate-catch on the live path (Enrich → AwaitReply → Assess)."""
    return bpmn.replace(
        '<bpmn:sequenceFlow id="Flow_Enrich_Assess" sourceRef="Task_EnrichPayment" targetRef="Task_AssessRepairability"/>',
        '<bpmn:intermediateCatchEvent id="AwaitReply"><bpmn:messageEventDefinition/></bpmn:intermediateCatchEvent>'
        '<bpmn:sequenceFlow id="fe_a" sourceRef="Task_EnrichPayment" targetRef="AwaitReply"/>'
        '<bpmn:sequenceFlow id="fa_a" sourceRef="AwaitReply" targetRef="Task_AssessRepairability"/>')


async def test_message_binding_bijection_ok(registered, cap_repo, schema_repo):
    # ADR-031: under the messages profile a message catch + its message binding validate cleanly.
    from amendia_bpmn import compute_sha256
    from app.validation.pack_validator import PackValidator
    v = PackValidator(cap_repo, schema_repo, profile="messages")
    d = manifest_dict()
    bpmn = _with_message_catch(load_bpmn())
    d["process"]["bpmn_sha256"] = compute_sha256(bpmn)
    d["bindings"].append({"element_id": "AwaitReply", "element_kind": "messageCatch",
                          "executor": {"type": "message", "message_name": "rfi_reply"}})
    report = await _validate(v, build(d), bpmn=bpmn)
    codes = _errs(report)
    assert not ({"orphan_binding", "unbound_task", "executor_kind_mismatch",
                 "message_name_missing", "bpmn_message_unsupported"} & codes), codes


async def test_message_binding_requires_name_and_profile(registered, cap_repo, schema_repo):
    from amendia_bpmn import compute_sha256
    from app.validation.pack_validator import PackValidator
    d = manifest_dict()
    bpmn = _with_message_catch(load_bpmn())
    d["process"]["bpmn_sha256"] = compute_sha256(bpmn)
    d["bindings"].append({"element_id": "AwaitReply", "element_kind": "messageCatch",
                          "executor": {"type": "message", "message_name": ""}})
    # empty message_name → flagged
    v = PackValidator(cap_repo, schema_repo, profile="messages")
    assert "message_name_missing" in _errs(await _validate(v, build(d), bpmn=bpmn))
    # under a lower profile the message construct is refused for activation
    v0 = PackValidator(cap_repo, schema_repo, profile="common_subset")
    assert "bpmn_message_unsupported" in _errs(await _validate(v0, build(d), bpmn=bpmn))


def _wrap_task_in_subprocess(bpmn: str, task_id: str) -> str:
    import re
    m = re.search(rf'<bpmn:(serviceTask|userTask) id="{task_id}".*?</bpmn:\1>', bpmn, re.DOTALL)
    block = m.group(0)
    bpmn = bpmn.replace(block, "")
    bpmn = re.sub(rf'(targetRef=")({task_id})(")', r'\1Sub\3', bpmn)
    bpmn = re.sub(rf'(sourceRef=")({task_id})(")', r'\1Sub\3', bpmn)
    sub = ('<bpmn:subProcess id="Sub"><bpmn:startEvent id="SubStart"><bpmn:outgoing>si</bpmn:outgoing></bpmn:startEvent>'
           + block +
           '<bpmn:endEvent id="SubEnd"><bpmn:incoming>so</bpmn:incoming></bpmn:endEvent>'
           f'<bpmn:sequenceFlow id="si" sourceRef="SubStart" targetRef="{task_id}"/>'
           f'<bpmn:sequenceFlow id="so" sourceRef="{task_id}" targetRef="SubEnd"/></bpmn:subProcess>')
    return bpmn.replace("</bpmn:process>", sub + "</bpmn:process>")


async def test_subprocess_bijection_includes_nested_task(registered, cap_repo, schema_repo):
    # ADR-032: a nested task joins the bijection (its existing binding still matches); the subProcess
    # container needs no binding. Under a lower profile the construct is refused.
    from amendia_bpmn import compute_sha256
    from app.validation.pack_validator import PackValidator
    bpmn = _wrap_task_in_subprocess(load_bpmn(), "Task_EnrichPayment")
    d = manifest_dict()
    d["process"]["bpmn_sha256"] = compute_sha256(bpmn)
    v = PackValidator(cap_repo, schema_repo, profile="subprocess")
    report = await _validate(v, build(d), bpmn=bpmn)
    codes = _errs(report)
    assert not ({"orphan_binding", "unbound_task", "bpmn_subprocess_unsupported"} & codes), codes
    # drop the nested task's binding → unbound_task
    d2 = manifest_dict()
    d2["process"]["bpmn_sha256"] = compute_sha256(bpmn)
    d2["bindings"] = [b for b in d2["bindings"] if b["element_id"] != "Task_EnrichPayment"]
    assert "unbound_task" in _errs(await _validate(v, build(d2), bpmn=bpmn))
    # refused under a lower profile
    v0 = PackValidator(cap_repo, schema_repo, profile="common_subset")
    assert "bpmn_subprocess_unsupported" in _errs(await _validate(v0, build(d), bpmn=bpmn))


def _retag(bpmn: str, task_id: str, new_kind: str) -> str:
    import re
    return re.sub(rf'<bpmn:serviceTask (id="{task_id}".*?)</bpmn:serviceTask>',
                  rf'<bpmn:{new_kind} \1</bpmn:{new_kind}>', bpmn, flags=re.DOTALL)


async def test_task_kinds_bijection_and_executor_category(registered, cap_repo, schema_repo):
    # ADR-033: a sendTask binds a capability executor and validates under the "tasks" profile.
    from amendia_bpmn import compute_sha256
    from app.validation.pack_validator import PackValidator
    bpmn = _retag(load_bpmn(), "Task_EnrichPayment", "sendTask")
    d = manifest_dict()
    d["process"]["bpmn_sha256"] = compute_sha256(bpmn)
    for b in d["bindings"]:
        if b["element_id"] == "Task_EnrichPayment":
            b["element_kind"] = "sendTask"
    v = PackValidator(cap_repo, schema_repo, profile="tasks")
    codes = _errs(await _validate(v, build(d), bpmn=bpmn))
    assert not ({"executor_kind_mismatch", "binding_kind_mismatch", "bpmn_task_kind_unsupported",
                 "orphan_binding"} & codes), codes
    # refused under a lower profile
    v0 = PackValidator(cap_repo, schema_repo, profile="common_subset")
    assert "bpmn_task_kind_unsupported" in _errs(await _validate(v0, build(d), bpmn=bpmn))


async def test_manual_task_bound_to_capability_is_mismatch(registered, cap_repo, schema_repo):
    from amendia_bpmn import compute_sha256
    from app.validation.pack_validator import PackValidator
    bpmn = _retag(load_bpmn(), "Task_EnrichPayment", "manualTask")
    d = manifest_dict()
    d["process"]["bpmn_sha256"] = compute_sha256(bpmn)
    for b in d["bindings"]:
        if b["element_id"] == "Task_EnrichPayment":
            b["element_kind"] = "manualTask"   # but keeps its capability executor → mismatch
    v = PackValidator(cap_repo, schema_repo, profile="tasks")
    assert "executor_kind_mismatch" in _errs(await _validate(v, build(d), bpmn=bpmn))


async def test_send_task_side_effect_guard_unchanged(registered, cap_repo, schema_repo):
    # a sendTask bound to a side_effectful capability still requires approve_actions (guard unchanged).
    from amendia_bpmn import compute_sha256
    from app.validation.pack_validator import PackValidator
    bpmn = _retag(load_bpmn(), "Task_ApplyRepair", "sendTask")
    d = manifest_dict()
    d["process"]["bpmn_sha256"] = compute_sha256(bpmn)
    for b in d["bindings"]:
        if b["element_id"] == "Task_ApplyRepair":
            b["element_kind"] = "sendTask"
            b["hitl"] = {"mode": "review_after", "role": "role.payments.ops_approver"}  # below floor
    v = PackValidator(cap_repo, schema_repo, profile="tasks")
    assert "side_effect_requires_approve_actions" in _errs(await _validate(v, build(d), bpmn=bpmn))
