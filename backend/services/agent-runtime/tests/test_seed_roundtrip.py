# tests/test_seed_roundtrip.py
"""Every seed file parses into its model and re-serializes equivalently."""
import json
from pathlib import Path

from app.config import settings
from app.models.artifact_schema import ArtifactSchemaRegistration
from app.models.capability import CapabilityDescriptor
from app.models.process_pack import ProcessPackManifest

SEED = Path(settings.SEED_DIR)


def _roundtrip(model_cls, path: Path):
    m = model_cls.model_validate_json(path.read_text())
    again = model_cls.model_validate(m.to_doc())
    assert again.to_doc() == m.to_doc()


def test_capabilities_roundtrip():
    files = sorted((SEED / "capabilities").glob("*.json"))
    assert len(files) == 10
    for f in files:
        _roundtrip(CapabilityDescriptor, f)


def test_artifact_schemas_roundtrip():
    files = sorted((SEED / "artifact-schemas").glob("*.json"))
    assert len(files) == 7
    for f in files:
        _roundtrip(ArtifactSchemaRegistration, f)


def test_manifest_roundtrip_and_bindings():
    m = ProcessPackManifest.model_validate_json((SEED / "manifest.json").read_text())
    assert len(m.bindings) == 12
    assert len(m.requires_capabilities) == 10
    assert len(m.artifacts) == 7
    again = ProcessPackManifest.model_validate(m.to_doc())
    assert again.to_doc() == m.to_doc()


def test_sample_exception_is_valid_json():
    data = json.loads((SEED / "sample-exception" / "wire-exception-ac01.json").read_text())
    assert data["exception_id"] == "EXC-2026-000123"
    assert data["reason_codes"] == ["AC01"]
