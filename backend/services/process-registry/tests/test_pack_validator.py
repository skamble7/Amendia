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
