# tests/test_seed_roundtrip.py
"""Every seed file parses into its model and re-serializes equivalently."""
import json
from pathlib import Path

from app.config import settings
from app.models.artifact_schema import ArtifactSchemaRegistration
from app.models.capability import CapabilityDescriptor
from app.models.process_pack import ProcessPackManifest

SEED = Path(settings.SEED_DIR)


def _seed_coords():
    raw = json.loads((SEED / "manifest.json").read_text())
    return raw["pack_key"], raw["version"]


def _roundtrip(model_cls, path: Path):
    # ADR-060: seed JSON carries no ownership — stamp the seed pack's coords, as the loader does at load time.
    doc = json.loads(path.read_text())
    doc["pack_key"], doc["pack_version"] = _seed_coords()
    m = model_cls.model_validate(doc)
    again = model_cls.model_validate(m.to_doc())
    assert again.to_doc() == m.to_doc()


def test_seeding_is_opt_in_no_code_default():
    # L2: the runtime carries no hardcoded seed path — a fresh Settings() has SEED_DIR unset, so with none
    # configured the service boots clean and loads nothing (the concrete path lives in test/dev config).
    from app.config import Settings
    assert Settings().SEED_DIR == ""


def test_capabilities_roundtrip():
    files = sorted((SEED / "capabilities").glob("*.json"))
    assert len(files) == 10
    for f in files:
        _roundtrip(CapabilityDescriptor, f)


def test_artifact_schemas_roundtrip():
    files = sorted((SEED / "artifact-schemas").glob("*.json"))
    assert len(files) == 9   # ADR-047 D2: + art.payment.info_resolution (needs-info human-authored exit)
    for f in files:
        _roundtrip(ArtifactSchemaRegistration, f)


def test_manifest_roundtrip_and_bindings():
    m = ProcessPackManifest.model_validate_json((SEED / "manifest.json").read_text())
    assert len(m.bindings) == 12
    assert len(m.requires_capabilities) == 10
    assert len(m.artifacts) == 8   # ADR-047 D2: orphan consumer schemas retired
    again = ProcessPackManifest.model_validate(m.to_doc())
    assert again.to_doc() == m.to_doc()


def test_sample_exception_is_valid_json():
    data = json.loads((SEED / "sample-trigger" / "wire-exception-ac01.json").read_text())
    assert data["exception_id"] == "EXC-2026-000123"
    assert data["reason_codes"] == ["AC01"]
