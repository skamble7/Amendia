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


async def test_declared_trigger_drives_triage_field_validation(registered, validator):
    # ADR-049 follow-up: a pack that DECLARES its own trigger validates triage against THAT schema, not the
    # deployment's (wire) sample envelopes — so a dining pack's `order_type` rule is clean, not a spurious
    # `triage_field_unknown` + a smoke "no match" against a foreign-domain sample.
    d = manifest_dict()
    d["trigger"] = "art.rest_stan.order_ticket@^1.0.0"
    d["triage_rules"] = [{"rule_id": "dine-in", "priority": 200,
                          "when": {"all": [{"field": "order_type", "op": "eq", "value": "dine_in"}]}}]
    trigger_schema = {"type": "object", "required": ["order_type"],
                      "properties": {"order_type": {"type": "string"}}}
    report = await validator.validate(build(d), load_bpmn(), sample_envelopes=[load_sample()],
                                      trigger_schema=trigger_schema)
    assert "triage_field_unknown" not in _errs(report), _errs(report)
    # the wire sample doesn't conform to the dining trigger → the smoke is SKIPPED (no spurious no-match).
    assert not any(f.code == "triage_rule_smoke" for f in report.findings)


async def test_no_declared_trigger_falls_back_to_sample_envelopes(registered, validator):
    # A pack with NO declared trigger keeps the old behaviour: triage fields come from the deployment sample
    # envelopes and the rule is smoked against them (the wire seed's rule MATCHes its own sample).
    d = manifest_dict()
    d["trigger"] = None
    report = await validator.validate(build(d), load_bpmn(), sample_envelopes=[load_sample()])
    assert "triage_field_unknown" not in _errs(report), _errs(report)
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
    await cap_repo.set_status("wire-repair-standard", "1.0.0", "cap.payment.sanctions_screen", "1.0.0", "deprecated")
    report = await _validate(validator, build(manifest_dict()))
    assert "capability_only_deprecated" in _errs(report)


async def test_side_effectful_at_review_after(registered, validator):
    # ADR-065: blocked WITHOUT a waiver; WITH a waiver the platform side-effect floor is cleared. (apply_repair
    # also declares min_hitl_mode=approve_actions — a NON-waivable floor — so the pack still fails on that; the
    # point here is the platform `side_effect_requires_approve_actions` rule itself is waived.)
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_ApplyRepair":
            b["hitl"] = {"mode": "review_after", "role": "role.payments.ops_approver"}
    assert "side_effect_requires_approve_actions" in _errs(await _validate(validator, build(d)))
    for b in d["bindings"]:
        if b["element_id"] == "Task_ApplyRepair":
            b["side_effect_waiver"] = _WAIVER
    errs = _errs(await _validate(validator, build(d)))
    assert "side_effect_requires_approve_actions" not in errs
    assert "hitl_below_capability_floor" in errs  # the capability author's floor is not waivable


async def test_binding_input_name_mismatch(registered, validator):
    # Inputs mirror the tool's field names and are NOT renameable — a name mismatch is still an error.
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_AssessRepairability":
            b["inputs"] = [{"name": "wrong_input", "schema": "art.payment.enrich_investigation_output@^1.0.0"}]
    report = await _validate(validator, build(d))
    assert "binding_io_mismatch" in _errs(report)


async def test_binding_output_rename_reconciles_by_schema(registered, validator):
    # ADR-051: a capability binding's OUTPUT name is operator-settable, so renaming it (same schema) must NOT
    # trip Stage-5 IO reconciliation — it reconciles by cardinality + schema, not name.
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_AssessRepairability":
            b["outputs"] = [{"name": "validation", "schema": "art.payment.assess_beneficiary_output@^1.0.0"}]
    report = await _validate(validator, build(d))
    assert "binding_io_mismatch" not in _errs(report)
    assert "binding_io_schema_incompatible" not in _errs(report)


async def test_binding_output_schema_mismatch_still_errors(registered, validator):
    # A renamed output whose SCHEMA actually differs (a range with no registered version) still errors.
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_AssessRepairability":
            b["outputs"] = [{"name": "validation", "schema": "art.payment.assess_beneficiary_output@^2.0.0"}]
    report = await _validate(validator, build(d))
    assert "binding_io_schema_incompatible" in _errs(report)


async def test_binding_output_cardinality_mismatch_errors(registered, validator):
    # Same-count is required: an extra (unexpected) output is a mismatch.
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_AssessRepairability":
            b["outputs"] = [
                {"name": "validation", "schema": "art.payment.assess_beneficiary_output@^1.0.0"},
                {"name": "extra", "schema": "art.payment.assess_beneficiary_output@^1.0.0"},
            ]
    report = await _validate(validator, build(d))
    assert "binding_io_mismatch" in _errs(report)


async def test_gateway_variable_on_non_required_field(registered, validator):
    d = manifest_dict()
    d["gateway_variables"][0]["variable"] = "beneficiary.proposed_correction"
    report = await _validate(validator, build(d))
    assert "gateway_variable_not_required" in _errs(report)


async def test_gateway_condition_unproduced_when_output_name_mismatches(registered, validator):
    # ADR-051: the runtime resolves a gateway condition against binding OUTPUT NAMES, so a condition whose first
    # segment names no produced output can never branch. With no authored gateway_variables entry to cover it,
    # that mismatch is an authoring-time error (was silent non-branching), not just a soft warning.
    d = manifest_dict()
    d["gateway_variables"] = []                       # un-authored → the raw-condition check runs
    for b in d["bindings"]:
        if b["element_id"] == "Task_AssessRepairability":   # condition reads beneficiary.repair_verdict
            b["outputs"] = [{"name": "validate_order_output", "schema": "art.payment.assess_beneficiary_output@^1.0.0"}]
    report = await _validate(validator, build(d))
    assert "gateway_condition_unproduced" in _errs(report)


async def test_gateway_condition_ok_when_output_name_matches(registered, validator):
    # The same pack with no authored gateway_variables but the ALIGNED output name (`beneficiary`) resolves —
    # the raw-condition check passes (only the soft gateway_without_variable note remains).
    d = manifest_dict()
    d["gateway_variables"] = []
    report = await _validate(validator, build(d))
    assert "gateway_condition_unproduced" not in _errs(report)


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


async def test_send_task_side_effect_guard_blocked_without_waiver_cleared_with(registered, cap_repo, schema_repo):
    # ADR-065: a sendTask bound to a side_effectful capability is blocked WITHOUT a waiver and has the platform
    # side-effect rule cleared WITH one (apply_repair's min_hitl_mode floor — not waivable — still applies).
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
    for b in d["bindings"]:
        if b["element_id"] == "Task_ApplyRepair":
            b["side_effect_waiver"] = _WAIVER
    assert "side_effect_requires_approve_actions" not in _errs(await _validate(v, build(d), bpmn=bpmn))


# --------------------------------------------------------------------------- #
# ADR-065 — the side-effect waiver + Part G/E fixes
# --------------------------------------------------------------------------- #
from app.validation.pack_validator import PackValidator  # noqa: E402

_WAIVER = {"justification": "Idempotent status handback to the external orchestrator; nothing to gate here."}


async def _register_seed_with(cap_repo, schema_repo, *, side_effectful=()):
    """Register seed schemas + caps, flipping the named capability_ids to side_effectful with NO
    min_hitl_mode — a floor-less real-world action (like the ADR's notify_pega), which is exactly the
    waivable case the seed caps (all min_hitl_mode=approve_actions) can't demonstrate."""
    from app.services.registration import register_schema
    from amendia_contracts.capability import CapabilityDescriptor
    from tests.conftest import load_schemas, load_capabilities
    for reg in load_schemas():
        await register_schema(reg, schema_repo)
    for cap in load_capabilities():
        if cap.capability_id in side_effectful:
            doc = cap.model_dump(mode="json", by_alias=True)
            doc["side_effect"] = "side_effectful"
            doc["constraints"] = {**(doc.get("constraints") or {}), "min_hitl_mode": None}
            cap = CapabilityDescriptor.model_validate(doc)
        await cap_repo.insert(cap)


def _mi_task(bpmn: str, task_id: str) -> str:
    """Inject multiInstanceLoopCharacteristics into a serviceTask so it becomes an MI host."""
    import re
    mi = ("<bpmn:multiInstanceLoopCharacteristics><bpmn:loopCardinality>3</bpmn:loopCardinality>"
          "</bpmn:multiInstanceLoopCharacteristics>")
    return re.sub(rf'(<bpmn:serviceTask id="{task_id}"[^>]*>)', rf'\1{mi}', bpmn)


async def test_assist_side_effect_at_manual_requires_waiver_and_waiver_clears(cap_repo, schema_repo):
    # ADR-065 Part G (amended 2026-09-01): a side-effectful assist runs in mode='execute' BEFORE the gate, so it
    # is un-gated by construction — even 'manual' (the normal human mode, rank 2) does NOT exempt it. Code:
    # `assist_side_effect_requires_waiver`. Task_ObtainInfo is a human task at hitl 'manual' with assist draft_rfi.
    await _register_seed_with(cap_repo, schema_repo, side_effectful=["cap.payment.draft_rfi"])
    v = PackValidator(cap_repo, schema_repo)
    d = manifest_dict()  # Task_ObtainInfo: human, hitl 'manual', assist cap.payment.draft_rfi (now side_effectful)
    assert "assist_side_effect_requires_waiver" in _errs(await _validate(v, build(d)))   # manual does not clear it
    # Deliverable 2 — the dead-waiver interaction: the same binding's waiver is LOAD-BEARING at manual, so the
    # pack validates clean with the `side_effect_waived` warning, NOT `side_effect_waiver_not_required`.
    for b in d["bindings"]:
        if b["element_id"] == "Task_ObtainInfo":
            b["side_effect_waiver"] = _WAIVER
    report = await _validate(v, build(d))
    errs2 = _errs(report)
    assert "assist_side_effect_requires_waiver" not in errs2
    assert "side_effect_waiver_not_required" not in errs2
    assert any(f.code == "side_effect_waived" and f.element_id == "Task_ObtainInfo" for f in report.findings)


async def test_waiver_allows_floorless_side_effectful_at_none(cap_repo, schema_repo):
    # The headline: a floor-less side_effectful capability bound at hitl 'none' is BLOCKED without a waiver and
    # CLEAN with one — the report carrying the loud `side_effect_waived` warning + justification.
    await _register_seed_with(cap_repo, schema_repo, side_effectful=["cap.payment.record_resolution"])
    v = PackValidator(cap_repo, schema_repo)
    d = manifest_dict()  # Task_RecordResolution binds record_resolution at hitl 'none'
    assert "side_effect_requires_approve_actions" in _errs(await _validate(v, build(d)))
    for b in d["bindings"]:
        if b["element_id"] == "Task_RecordResolution":
            b["side_effect_waiver"] = _WAIVER
    report = await _validate(v, build(d))
    assert report.ok, report.error_codes()
    waived = [f for f in report.findings if f.code == "side_effect_waived"]
    assert waived and waived[0].element_id == "Task_RecordResolution"
    assert _WAIVER["justification"] in waived[0].message


async def test_waiver_capability_mismatch_rejected_naming_both_ids(cap_repo, schema_repo):
    # ADR-065 P4a (D2): a hand-built manifest pairing a waiver with a DIFFERENT capability → the bond check
    # catches it. This is the only check that catches a manifest that never came through the registry.
    await _register_seed_with(cap_repo, schema_repo, side_effectful=["cap.payment.record_resolution"])
    v = PackValidator(cap_repo, schema_repo)
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_RecordResolution":
            b["side_effect_waiver"] = {**_WAIVER, "waived_capability_id": "cap.payment.execute_return"}  # wrong bond
    report = await _validate(v, build(d))
    assert "side_effect_waiver_capability_mismatch" in _errs(report)
    msg = next(f.message for f in report.findings if f.code == "side_effect_waiver_capability_mismatch")
    assert "cap.payment.execute_return" in msg and "cap.payment.record_resolution" in msg   # names BOTH ids


async def test_waiver_matching_bond_is_clean(cap_repo, schema_repo):
    # A correctly-bonded waiver validates exactly as an unbonded one did — clean, with the side_effect_waived
    # warning and NO mismatch / NO unbonded warning.
    await _register_seed_with(cap_repo, schema_repo, side_effectful=["cap.payment.record_resolution"])
    v = PackValidator(cap_repo, schema_repo)
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_RecordResolution":
            b["side_effect_waiver"] = {**_WAIVER, "waived_by": "usr-o", "waived_at": "2026-09-01T00:00:00Z",
                                       "waived_capability_id": "cap.payment.record_resolution"}
    report = await _validate(v, build(d))
    assert report.ok, report.error_codes()
    codes = {f.code for f in report.findings}
    assert "side_effect_waived" in codes
    assert "side_effect_waiver_capability_mismatch" not in codes and "side_effect_waiver_unbonded" not in codes


async def test_waiver_unbonded_is_a_warning_not_an_error(cap_repo, schema_repo):
    # ADR-065 P4a (D3): a load-bearing waiver with NO bond is a legacy (pre-P4a) waiver — a warning, not an error;
    # the pack still validates.
    await _register_seed_with(cap_repo, schema_repo, side_effectful=["cap.payment.record_resolution"])
    v = PackValidator(cap_repo, schema_repo)
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_RecordResolution":
            b["side_effect_waiver"] = _WAIVER   # justification only — no provenance
    report = await _validate(v, build(d))
    assert report.ok, report.error_codes()
    assert any(f.code == "side_effect_waiver_unbonded" and f.element_id == "Task_RecordResolution"
               for f in report.findings)


async def test_assist_waiver_bond_mismatch_rejected(cap_repo, schema_repo):
    # ADR-065 P4a (D2, assist): a waiver on a human binding bonds to the ASSIST (Part G). A wrong bond is caught.
    await _register_seed_with(cap_repo, schema_repo, side_effectful=["cap.payment.draft_rfi"])
    v = PackValidator(cap_repo, schema_repo)
    d = manifest_dict()  # Task_ObtainInfo: human at 'manual', assist cap.payment.draft_rfi (now side_effectful)
    for b in d["bindings"]:
        if b["element_id"] == "Task_ObtainInfo":
            b["side_effect_waiver"] = {**_WAIVER, "waived_capability_id": "cap.payment.notify_parties"}  # not the assist
    report = await _validate(v, build(d))
    assert "side_effect_waiver_capability_mismatch" in _errs(report)
    msg = next(f.message for f in report.findings if f.code == "side_effect_waiver_capability_mismatch")
    assert "cap.payment.draft_rfi" in msg   # names the ASSIST id, not the human role


async def test_waiver_on_read_only_is_dead(registered, validator):
    # A waiver where the capability is read_only does nothing → error (dead waivers must not accumulate).
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_EnrichPayment":   # read_only, hitl none
            b["side_effect_waiver"] = _WAIVER
    assert "side_effect_waiver_not_required" in _errs(await _validate(validator, build(d)))


async def test_waiver_on_already_gated_is_dead(registered, validator):
    # A waiver where the binding already gates at approve_actions does nothing → error.
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_ApplyRepair":     # side_effectful, already approve_actions
            b["side_effect_waiver"] = _WAIVER
    assert "side_effect_waiver_not_required" in _errs(await _validate(validator, build(d)))


async def test_waiver_cannot_pass_min_hitl_mode(registered, validator):
    # ADR-065 Part B: the capability author's min_hitl_mode floor is NOT waivable. apply_repair is side_effectful
    # with min_hitl_mode approve_actions; a waiver at 'none' suppresses the platform floor (side_effect_waived)
    # but hitl_below_capability_floor still fires — the pack stays blocked.
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_ApplyRepair":
            b["hitl"] = {"mode": "none"}
            b["side_effect_waiver"] = _WAIVER
    errs = _errs(await _validate(validator, build(d)))
    assert "hitl_below_capability_floor" in errs
    assert "side_effect_requires_approve_actions" not in errs   # the platform floor IS waived


async def test_human_executor_at_none_rejected(registered, validator):
    # ADR-065 Part G: a human executor bound at hitl 'none' is a validation error (runtime would raise).
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_ApproveRepair":   # human executor
            b["hitl"] = {"mode": "none"}
    assert "hitl_none_on_human_executor" in _errs(await _validate(validator, build(d)))


async def test_multi_instance_side_effect_blocked_even_with_waiver(cap_repo, schema_repo):
    # ADR-065 Part E: a side_effectful capability may not be a multi-instance host, waiver or not.
    from amendia_bpmn import compute_sha256
    await _register_seed_with(cap_repo, schema_repo, side_effectful=["cap.payment.record_resolution"])
    v = PackValidator(cap_repo, schema_repo)
    bpmn = _mi_task(load_bpmn(), "Task_RecordResolution")
    d = manifest_dict()
    d["process"]["bpmn_sha256"] = compute_sha256(bpmn)
    for b in d["bindings"]:
        if b["element_id"] == "Task_RecordResolution":
            b["side_effect_waiver"] = _WAIVER   # even waived, still blocked
    assert "multi_instance_side_effect_unsupported" in _errs(await _validate(v, build(d), bpmn=bpmn))


async def test_sod_over_ungated_element_warns(cap_repo, schema_repo):
    # ADR-065 SoD consequence: distinct_actor over an un-gated (hitl none) element writes no human actor_log.
    await _register_seed_with(cap_repo, schema_repo, side_effectful=["cap.payment.record_resolution"])
    v = PackValidator(cap_repo, schema_repo)
    d = manifest_dict()
    for b in d["bindings"]:
        if b["element_id"] == "Task_RecordResolution":
            b["side_effect_waiver"] = _WAIVER  # keep the pack otherwise clean
    d["policies"] = {"separation_of_duties": [
        {"constraint": "distinct_actor", "elements": ["Task_RecordResolution", "Task_ApproveRepair"]}]}
    report = await _validate(v, build(d))
    assert any(f.code == "sod_element_ungated" and f.element_id == "Task_RecordResolution" for f in report.findings)


async def test_read_only_with_ack_shape_output_warns(registered, cap_repo, schema_repo):
    # ADR-065 Part H: a read_only capability whose OUTPUT carries the acknowledgement shape
    # (acknowledged/action_id/status) that infers a side effect → non-blocking warning (likely a downgrade to
    # dodge the gate). Register resolution_record at a higher version with the ack shape so the validator
    # resolves it as latest; record_resolution stays read_only.
    from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
    # Insert directly (bypassing the registration backward-compat gate, irrelevant here) at a higher version so
    # the validator resolves this ack-shaped schema as latest for record_resolution's read_only output.
    ack = ArtifactSchemaRegistration.model_validate({
        "artifact_key": "art.payment.resolution_record", "version": "1.1.0",
        "pack_key": "wire-repair-standard", "pack_version": "1.0.0", "title": "ack", "compatibility": "backward",
        "json_schema": {"type": "object", "additionalProperties": False,
                        "properties": {"acknowledged": {"type": "boolean"}, "action_id": {"type": "string"},
                                       "status": {"type": "string"}},
                        "required": ["acknowledged", "action_id", "status"]},
        "status": "active"})
    await schema_repo.insert(ack)
    report = await _validate(PackValidator(cap_repo, schema_repo), build(manifest_dict()))
    assert any(f.code == "side_effect_downgraded_from_inference" and f.element_id == "Task_RecordResolution"
               for f in report.findings)


async def test_read_only_ack_downgrade_survives_real_infer_path(registered, cap_repo, schema_repo):
    # ADR-065 P1 follow-up (D2): lock the Part-H signal onto the REAL onboarding path — a genuinely mislabeled tool
    # (ack-shaped output_schema, operator sets read_only) driven through infer_capability → normalize_artifact_schema
    # → register → validate STILL warns. This guards the property the P1 report relied on: normalize deepcopies and
    # only ADDS keys, so top-level `properties` survives verbatim; if a future normalize ever dropped them,
    # carries_ack_shape would go blind and this test — not just the hand-inserted one — would catch it.
    from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
    from app.services.mcp_introspect import carries_ack_shape, infer_capability

    ack_output = {"type": "object",
                  "properties": {"acknowledged": {"type": "boolean"}, "action_id": {"type": "string"},
                                 "status": {"type": "string"}},
                  "required": ["acknowledged", "action_id", "status"]}
    _in, out_art, _cap, _w = infer_capability(
        tool="record_resolution", endpoint="http://dinein-mcp:8070/mcp", transport="streamable_http", headers={},
        domain="payment", input_schema={"type": "object", "properties": {"case_id": {"type": "string"}}},
        output_schema=ack_output, input_artifact_key="art.payment.resolution_record_input",
        output_artifact_key="art.payment.resolution_record", capability_id="cap.payment.record_resolution",
        artifact_version="1.1.0", capability_version="1.0.0",
        side_effect="read_only",                       # <-- the operator MISLABEL the warning must catch
        idempotent=None, min_hitl_mode=None, title="Record resolution", description="record")
    # the schema went through normalize_artifact_schema and still carries the ack shape (the property under test)
    assert carries_ack_shape(out_art.json_schema)
    await schema_repo.insert(ArtifactSchemaRegistration.model_validate({
        "artifact_key": out_art.artifact_key, "version": out_art.version, "pack_key": "wire-repair-standard",
        "pack_version": "1.0.0", "title": "ack", "compatibility": "backward",
        "json_schema": out_art.json_schema, "status": "active"}))
    report = await _validate(PackValidator(cap_repo, schema_repo), build(manifest_dict()))
    assert any(f.code == "side_effect_downgraded_from_inference" and f.element_id == "Task_RecordResolution"
               for f in report.findings)
