# tests/test_decision_validation.py
"""ADR-037 — registry validation for the native DMN `decision` capability kind.

Rebinds Task_AssessRepairability (serviceTask → capability, produces the repair_verdict) to a
`kind: decision` capability whose inline table is validated by the shared evaluator. Covers accept
(opt-in) plus each table/mapping refusal code.
"""
import json

import pytest

from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest
from tests.conftest import SEED, load_bpmn, load_sample

_CAP = "cap.payment.repair_decision"


def _good_table():
    return {
        "hit_policy": "FIRST",
        "inputs": [{"expression": "dossier.gpi_status.status", "type": "string"}],
        "outputs": [{"name": "repair_verdict", "type": "string"}],
        "rules": [
            {"when": ['"returned"'], "then": ["needs_info"]},
            {"when": ["-"], "then": ["repairable"]},
        ],
    }


def _decision_descriptor(table=None) -> CapabilityDescriptor:
    return CapabilityDescriptor.model_validate({
        "descriptor_version": "1.0", "capability_id": _CAP, "version": "1.0.0",
        "title": "Repair decision (DMN)", "kind": "decision", "side_effect": "read_only",
        "idempotent": True,
        "inputs": [{"name": "dossier", "schema": "art.payment.investigation_dossier@^1.0.0"}],
        "outputs": [{"name": "beneficiary", "schema": "art.payment.repair_verdict@^1.0.0"}],
        "runtime": {"kind": "decision", "table": table if table is not None else _good_table()},
        "constraints": {"timeout_seconds": 30, "max_retries": 0, "min_hitl_mode": "none"},
        "status": "active",
    })


def _rebind() -> dict:
    d = json.loads((SEED / "manifest.json").read_text())
    for b in d["bindings"]:
        if b["element_id"] == "Task_AssessRepairability":
            b["executor"]["capability"] = f"{_CAP}@^1.0.0"
    d["requires_capabilities"].append({"ref": f"{_CAP}@^1.0.0"})
    return d


async def _validate(validator, d):
    return await validator.validate(ProcessPackManifest.model_validate(d), load_bpmn(),
                                    sample_envelopes=[load_sample()])


def _errs(report):
    return set(report.error_codes())


@pytest.fixture
async def registered_with_decision(registered, cap_repo):
    async def _register(table=None):
        await cap_repo.insert(_decision_descriptor(table))
        return cap_repo
    return _register


# --------------------------------------------------------------------------- #
async def test_valid_decision_pack_passes(registered_with_decision, validator):
    await registered_with_decision()
    report = await _validate(validator, _rebind())
    assert report.ok, report.error_codes()


async def test_plain_businessrule_capability_still_validates(registered, validator):
    # The unmodified standard pack (no decision kind) still validates — native DMN is opt-in.
    report = await _validate(validator, json.loads((SEED / "manifest.json").read_text()))
    assert report.ok, report.error_codes()


async def test_malformed_table_no_rules(registered_with_decision, validator):
    t = _good_table(); t["rules"] = []
    await registered_with_decision(t)
    assert "dmn_table_malformed" in _errs(await _validate(validator, _rebind()))


async def test_unknown_hit_policy(registered_with_decision, validator):
    t = _good_table(); t["hit_policy"] = "RANDOM"
    await registered_with_decision(t)
    assert "dmn_unknown_hit_policy" in _errs(await _validate(validator, _rebind()))


async def test_bad_unary_test(registered_with_decision, validator):
    t = _good_table(); t["rules"][0]["when"] = ["returned"]  # unquoted string → illegal literal
    await registered_with_decision(t)
    assert "dmn_bad_unary_test" in _errs(await _validate(validator, _rebind()))


async def test_input_unresolved(registered_with_decision, validator):
    t = _good_table(); t["inputs"] = [{"expression": "nope.status"}]  # root not a declared input
    await registered_with_decision(t)
    assert "dmn_input_unresolved" in _errs(await _validate(validator, _rebind()))


async def test_output_unmapped(registered_with_decision, validator):
    t = _good_table(); t["outputs"] = [{"name": "bogus_field"}]
    t["rules"] = [{"when": ['"returned"'], "then": ["x"]}, {"when": ["-"], "then": ["y"]}]
    await registered_with_decision(t)
    assert "dmn_output_unmapped" in _errs(await _validate(validator, _rebind()))


async def test_static_rules_overlap(registered_with_decision, validator):
    t = _good_table()
    t["hit_policy"] = "UNIQUE"
    t["rules"] = [
        {"when": ['"returned"'], "then": ["needs_info"]},
        {"when": ['"returned"'], "then": ["repairable"]},  # identical input cell → overlap
    ]
    await registered_with_decision(t)
    assert "dmn_rules_overlap" in _errs(await _validate(validator, _rebind()))
