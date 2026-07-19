# tests/test_reduce_validation.py
"""ADR-038 — registry validation for the `reduce` capability kind.

Validates the real ``wire-repair-screening`` demo pack (multi-instance screen → reduce → gateway) via
the registry PackValidator (at the ``common_executable`` profile MI needs), plus each ``reduce_*``
refusal by mutating the reduce config.
"""
from pathlib import Path

import pytest

from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest
from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from app.validation.pack_validator import PackValidator

SCREENING = Path(__file__).resolve().parents[2] / "agent-runtime" / "seed" / "wire-repair-screening"
_CAP = "cap.screening.reduce_hits"


def _good_config():
    return {"op": "first", "source": "screening", "item_path": "verdict",
            "predicate": '= "hit"', "output_field": "matched"}


def _reduce_descriptor(config=None) -> CapabilityDescriptor:
    return CapabilityDescriptor.model_validate({
        "descriptor_version": "1.0", "capability_id": _CAP, "version": "1.0.0",
        "title": "reduce hits", "kind": "reduce", "side_effect": "read_only", "idempotent": True,
        "inputs": [{"name": "screening", "schema": "art.screening.party_result@^1.0.0"}],
        "outputs": [{"name": "summary", "schema": "art.screening.summary@^1.0.0"}],
        "runtime": {"kind": "reduce", "config": config if config is not None else _good_config()},
        "constraints": {"timeout_seconds": 30, "max_retries": 0, "min_hitl_mode": "none"},
        "status": "active",
    })


@pytest.fixture
async def registered_screening(cap_repo, schema_repo):
    from app.services.registration import register_schema
    for f in sorted((SCREENING / "artifact-schemas").glob("*.json")):
        await register_schema(ArtifactSchemaRegistration.model_validate_json(f.read_text()), schema_repo)
    await cap_repo.insert(CapabilityDescriptor.model_validate_json(
        (SCREENING / "capabilities" / "cap.screening.screen_party.json").read_text()))

    async def _register_reduce(config=None):
        await cap_repo.insert(_reduce_descriptor(config))
    return _register_reduce


async def _validate(cap_repo, schema_repo):
    validator = PackValidator(cap_repo, schema_repo, profile="common_executable")
    manifest = ProcessPackManifest.model_validate_json((SCREENING / "manifest.json").read_text())
    bpmn = (SCREENING / "wire-repair-screening.bpmn").read_text()
    return await validator.validate(manifest, bpmn)


def _errs(report):
    return set(report.error_codes())


# --------------------------------------------------------------------------- #
async def test_valid_reduce_pack_passes(registered_screening, cap_repo, schema_repo):
    await registered_screening()
    report = await _validate(cap_repo, schema_repo)
    assert report.ok, report.error_codes()


async def test_unknown_op(registered_screening, cap_repo, schema_repo):
    c = _good_config(); c["op"] = "frobnicate"
    await registered_screening(c)
    assert "reduce_unknown_op" in _errs(await _validate(cap_repo, schema_repo))


async def test_bad_predicate(registered_screening, cap_repo, schema_repo):
    c = _good_config(); c["predicate"] = "hit"  # unquoted string → illegal unary test
    await registered_screening(c)
    assert "reduce_bad_predicate" in _errs(await _validate(cap_repo, schema_repo))


async def test_predicate_required(registered_screening, cap_repo, schema_repo):
    c = {"op": "any", "source": "screening", "item_path": "verdict", "output_field": "matched"}
    await registered_screening(c)
    assert "reduce_predicate_required" in _errs(await _validate(cap_repo, schema_repo))


async def test_source_missing(registered_screening, cap_repo, schema_repo):
    c = _good_config(); c["source"] = "nope"  # not a declared binding input
    await registered_screening(c)
    assert "reduce_source_missing" in _errs(await _validate(cap_repo, schema_repo))


async def test_output_unmapped(registered_screening, cap_repo, schema_repo):
    c = _good_config(); c["output_field"] = "bogus"  # not a field of the summary schema
    await registered_screening(c)
    assert "reduce_output_unmapped" in _errs(await _validate(cap_repo, schema_repo))


async def test_numeric_type(registered_screening, cap_repo, schema_repo):
    # a numeric op reading 'party' (declared type string) → reduce_numeric_type
    c = {"op": "sum", "source": "screening", "item_path": "party", "output_field": "matched"}
    await registered_screening(c)
    assert "reduce_numeric_type" in _errs(await _validate(cap_repo, schema_repo))
