# tests/test_call_validation.py
"""ADR-039 — registry validation + activation pinning for cross-pack callActivity.

Activates the callee pack(s) first, then validates the caller through the real PackValidator (with a
pack repo) and pins the callee at activation. Covers the accept path + each call_activity refusal.
"""
import json
from pathlib import Path

import pytest

from amendia_bpmn import parse, required_profile
from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest
from app.models.registry import Resolution
from app.services.activation import resolve_pins
from app.validation.pack_validator import PackValidator

COMPOSE = Path(__file__).resolve().parents[2] / "agent-runtime" / "seed"


async def _register(pack: str, cap_repo, schema_repo) -> ProcessPackManifest:
    from app.dal.base import DuplicateError
    from app.services.registration import register_schema
    d = COMPOSE / pack
    for f in sorted((d / "artifact-schemas").glob("*.json")):
        try:
            await register_schema(ArtifactSchemaRegistration.model_validate_json(f.read_text()), schema_repo)
        except DuplicateError:
            pass  # shared schema already registered by another compose pack
    for f in sorted((d / "capabilities").glob("*.json")):
        try:
            await cap_repo.insert(CapabilityDescriptor.model_validate_json(f.read_text()))
        except DuplicateError:
            pass
    return ProcessPackManifest.model_validate_json((d / "manifest.json").read_text())


async def _activate(pack: str, cap_repo, schema_repo, pack_repo) -> ProcessPackManifest:
    mf = await _register(pack, cap_repo, schema_repo)
    await pack_repo.insert(mf)
    bpmn = (COMPOSE / pack / mf.process.bpmn_file).read_text()
    model, _ = parse(bpmn, mf.process.process_id)
    res, caps = await resolve_pins(mf, cap_repo, schema_repo,
                                   required_execution_profile=required_profile(model), pack_repo=pack_repo)
    await pack_repo.activate(mf.pack_key, mf.version, resolved_caps=caps, resolution=res.to_doc())
    return mf


async def _insert_active(pack: str, pack_repo) -> None:
    """Insert a pack as active WITHOUT validating it (for building a cyclic graph)."""
    mf = ProcessPackManifest.model_validate_json((COMPOSE / pack / "manifest.json").read_text())
    await pack_repo.insert(mf)
    await pack_repo.activate(mf.pack_key, mf.version, resolved_caps={},
                             resolution=Resolution(required_execution_profile="common_executable").to_doc())


async def _validate_caller(pack: str, cap_repo, schema_repo, pack_repo, *, mutate=None):
    mf = await _register(pack, cap_repo, schema_repo)
    if mutate:
        mf = mutate(mf)
    bpmn = (COMPOSE / pack / mf.process.bpmn_file).read_text()
    validator = PackValidator(cap_repo, schema_repo, profile="common_executable", pack_repo=pack_repo)
    return await validator.validate(mf, bpmn)


def _errs(report):
    return set(report.error_codes())


# --------------------------------------------------------------------------- #
async def test_valid_caller_passes_and_pins_callee(cap_repo, schema_repo, pack_repo):
    await _activate("compose-leaf", cap_repo, schema_repo, pack_repo)
    report = await _validate_caller("compose-caller", cap_repo, schema_repo, pack_repo)
    assert report.ok, report.error_codes()


async def test_activation_pins_callee_version(cap_repo, schema_repo, pack_repo):
    await _activate("compose-leaf", cap_repo, schema_repo, pack_repo)
    mf = await _register("compose-caller", cap_repo, schema_repo)
    res, _ = await resolve_pins(mf, cap_repo, schema_repo,
                                required_execution_profile="common_executable", pack_repo=pack_repo)
    pins = {c.element: c for c in res.call_activities}
    assert pins["CA_Leaf"].pack_key == "compose-leaf"
    assert pins["CA_Leaf"].version == "1.0.0"                 # pinned exact, reproducible
    assert pins["CA_Leaf"].input_map == {"inp": "seed"}


async def test_pack_unresolved_when_callee_not_active(cap_repo, schema_repo, pack_repo):
    # compose-leaf NOT activated → the caller's callee can't resolve.
    report = await _validate_caller("compose-caller", cap_repo, schema_repo, pack_repo)
    assert "call_activity_pack_unresolved" in _errs(report)


async def test_io_unmapped_missing_required_input(cap_repo, schema_repo, pack_repo):
    await _activate("compose-leaf", cap_repo, schema_repo, pack_repo)

    def drop_input_map(mf):
        for b in mf.bindings:
            if b.element_id == "CA_Leaf":
                b.executor.input_map = {}  # callee requires 'inp'
        return mf
    report = await _validate_caller("compose-caller", cap_repo, schema_repo, pack_repo, mutate=drop_input_map)
    assert "call_activity_io_unmapped" in _errs(report)


async def test_io_unmapped_unknown_output(cap_repo, schema_repo, pack_repo):
    await _activate("compose-leaf", cap_repo, schema_repo, pack_repo)

    def bad_output(mf):
        for b in mf.bindings:
            if b.element_id == "CA_Leaf":
                b.executor.output_map = {"got": "nonexistent_output"}
        return mf
    report = await _validate_caller("compose-caller", cap_repo, schema_repo, pack_repo, mutate=bad_output)
    assert "call_activity_io_unmapped" in _errs(report)


async def test_io_mismatch_source_not_produced_upstream(cap_repo, schema_repo, pack_repo):
    await _activate("compose-leaf", cap_repo, schema_repo, pack_repo)

    def bad_source(mf):
        for b in mf.bindings:
            if b.element_id == "CA_Leaf":
                b.executor.input_map = {"inp": "not_produced"}
        return mf
    report = await _validate_caller("compose-caller", cap_repo, schema_repo, pack_repo, mutate=bad_source)
    assert "call_activity_io_mismatch" in _errs(report)


async def test_cycle_refused(cap_repo, schema_repo, pack_repo):
    # cyc-a → cyc-b → cyc-a. Insert cyc-b active, then validate cyc-a.
    await _insert_active("compose-cyc-b", pack_repo)
    report = await _validate_caller("compose-cyc-a", cap_repo, schema_repo, pack_repo)
    assert "bpmn_call_activity_cycle" in _errs(report)


async def test_depth_refused(cap_repo, schema_repo, pack_repo, monkeypatch):
    import app.validation.call as callmod
    monkeypatch.setattr(callmod, "MAX_CALL_DEPTH", 1)
    await _activate("compose-leaf", cap_repo, schema_repo, pack_repo)
    await _activate("compose-mid", cap_repo, schema_repo, pack_repo)
    report = await _validate_caller("compose-top", cap_repo, schema_repo, pack_repo)  # top→mid→leaf = depth 2
    assert "bpmn_call_activity_depth" in _errs(report)
