# tests/test_seed_pack_registry_gate.py
"""ADR-047 D2 parity gate — every seed/fixture pack must be REGISTRY-valid.

agent-runtime running a pack green does NOT prove the registry would accept it: the runtime's PackBundle
loader is looser than registry onboarding — it tolerates a missing ``json_schema.$id`` and does NOT reconcile
binding⇄capability IO. That gap is exactly how the flipped-seed ``binding_io_mismatch`` hid until this pass.

This test closes it: for every pack under ``agent-runtime/seed`` it registers the pack's schemas + capabilities,
derives the BPMN conformance profile the diagram needs (``required_profile`` — the same derivation the
onboarding service uses, never operator-supplied), and runs the real ``PackValidator`` under that profile,
asserting the report is clean. A failure here is a real seed defect to fix — never a test to loosen.

(NB: ``onboard_seed.onboard`` is a dev-seed shortcut that hardcodes ``common_subset``; it is fine for the
production wire-repair-standard seed but would wrongly reject the advanced construct fixtures. This gate uses
the production ``required_profile`` derivation instead, so MI / call-activity / scope / decision packs are
judged under the profile they actually run at.)
"""
from __future__ import annotations

from pathlib import Path

import pytest
from mongomock_motor import AsyncMongoMockClient

from amendia_bpmn import parse
from amendia_bpmn.compilability import required_profile
from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest
from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.capability_repo import CapabilityRepository
from app.db.mongo import ARTIFACT_SCHEMAS, CAPABILITIES, create_indexes
from app.services.registration import register_schema
from app.validation.pack_validator import PackValidator

SEED_ROOT = Path(__file__).resolve().parents[2] / "agent-runtime" / "seed"
PACKS = sorted((p.parent for p in SEED_ROOT.glob("*/manifest.json")), key=lambda p: p.name)


def _load_samples(pack_dir: Path) -> list:
    import json
    d = pack_dir / "sample-trigger"
    return [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))] if d.exists() else []


async def _register(pack_dir: Path, cap_repo, schema_repo):
    import json
    # ADR-060: seed JSON carries no ownership — stamp this pack's (pack_key, version) at load so the
    # pack-scoped validator finds the pack's own owned rows.
    m = json.loads((pack_dir / "manifest.json").read_text())
    pk, ver = m["pack_key"], m["version"]
    for f in sorted((pack_dir / "artifact-schemas").glob("*.json")):
        doc = json.loads(f.read_text())
        doc["pack_key"], doc["pack_version"] = pk, ver
        await register_schema(ArtifactSchemaRegistration.model_validate(doc), schema_repo)
    for f in sorted((pack_dir / "capabilities").glob("*.json")):
        doc = json.loads(f.read_text())
        doc["pack_key"], doc["pack_version"] = pk, ver
        await cap_repo.insert(CapabilityDescriptor.model_validate(doc))


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda p: p.name)
async def test_seed_pack_is_registry_valid(pack_dir: Path):
    # A fresh in-memory registry per pack — each must stand alone through the real validator.
    db = AsyncMongoMockClient()[f"gate_{pack_dir.name}"]
    await create_indexes(db)
    cap_repo = CapabilityRepository(db[CAPABILITIES])
    schema_repo = ArtifactSchemaRepository(db[ARTIFACT_SCHEMAS])
    await _register(pack_dir, cap_repo, schema_repo)

    manifest = ProcessPackManifest.model_validate_json((pack_dir / "manifest.json").read_text())
    bpmn = (pack_dir / manifest.process.bpmn_file).read_text()
    model, _ = parse(bpmn, manifest.process.process_id, profile="common_executable")
    assert model is not None, f"{pack_dir.name}: BPMN failed to parse"
    profile = required_profile(model)  # the conformance level the diagram needs (production derivation)

    validator = PackValidator(cap_repo, schema_repo, profile=profile)
    report = await validator.validate(manifest, bpmn, sample_envelopes=_load_samples(pack_dir))
    assert report.ok, f"{pack_dir.name} (profile={profile}) is NOT registry-valid: {report.error_codes()}"


def test_gate_covers_every_seed_pack():
    # Guard the guard: a pack added under seed/ must be picked up here (no silent gap).
    names = {p.name for p in PACKS}
    assert {"wire-repair-standard", "wire-repair-agentic"} <= names, names
