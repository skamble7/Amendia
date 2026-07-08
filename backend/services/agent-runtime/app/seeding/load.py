# app/seeding/load.py
"""Idempotent seed loader for the wire-repair-standard process pack.

Pipeline per run:
  1. Parse every seed file through its Pydantic contract model.
  2. Meta-validate each artifact schema's embedded ``json_schema`` (draft 2020-12).
  3. Compute the BPMN sha256 from the actual file and inject it into the manifest.
  4. Upsert idempotently by natural key: absent → insert; identical → no-op;
     changed for the same (immutable) version → refuse with a clear error.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from jsonschema import Draft202012Validator

from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.capability_repo import CapabilityRepository
from app.dal.pack_repo import ProcessPackRepository
from app.dal.sample_repo import SampleExceptionRepository
from app.db.mongo import (
    ARTIFACT_SCHEMAS,
    CAPABILITIES,
    PROCESS_PACKS,
    SAMPLE_EXCEPTIONS,
    MongoClient,
)
from app.models.artifact_schema import ArtifactSchemaRegistration
from app.models.capability import CapabilityDescriptor
from app.models.process_pack import ProcessPackManifest

logger = logging.getLogger(__name__)

_IGNORE_KEYS = {"created_at", "updated_at", "bpmn_xml"}


class SeedConflictError(Exception):
    """Content changed for an already-seeded, immutable version."""


@dataclass
class SeedReport:
    inserted: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "inserted": self.inserted,
            "skipped": self.skipped,
            "inserted_count": len(self.inserted),
            "skipped_count": len(self.skipped),
        }


def _strip(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in _IGNORE_KEYS}


class SeedLoader:
    def __init__(self, seed_dir: str | Path) -> None:
        self.seed_dir = Path(seed_dir)

    # -- readers ---------------------------------------------------------- #

    def _bpmn_path_and_sha(self, manifest_raw: Dict[str, Any]) -> tuple[Path, str]:
        bpmn_path = self.seed_dir / manifest_raw["process"]["bpmn_file"]
        sha = hashlib.sha256(bpmn_path.read_bytes()).hexdigest()
        return bpmn_path, sha

    def load_manifest(self) -> tuple[ProcessPackManifest, str]:
        """Parse the manifest with the real BPMN sha256 injected; return (manifest, bpmn_xml)."""
        raw = json.loads((self.seed_dir / "manifest.json").read_text())
        bpmn_path, sha = self._bpmn_path_and_sha(raw)
        raw.setdefault("process", {})["bpmn_sha256"] = sha  # inject computed digest
        manifest = ProcessPackManifest.model_validate(raw)
        return manifest, bpmn_path.read_text()

    def load_capabilities(self) -> List[CapabilityDescriptor]:
        out = []
        for f in sorted((self.seed_dir / "capabilities").glob("*.json")):
            out.append(CapabilityDescriptor.model_validate_json(f.read_text()))
        return out

    def load_artifact_schemas(self) -> List[ArtifactSchemaRegistration]:
        out = []
        for f in sorted((self.seed_dir / "artifact-schemas").glob("*.json")):
            reg = ArtifactSchemaRegistration.model_validate_json(f.read_text())
            # Meta-validate the embedded schema as a well-formed draft 2020-12 schema.
            Draft202012Validator.check_schema(reg.json_schema)
            if reg.json_schema.get("type") != "object":
                raise ValueError(f"{reg.artifact_key}: root json_schema type must be 'object'")
            if "$id" not in reg.json_schema:
                logger.warning("%s: json_schema is missing $id", reg.artifact_key)
            if reg.json_schema.get("additionalProperties") is not False:
                logger.warning("%s: json_schema should set additionalProperties=false", reg.artifact_key)
            out.append(reg)
        return out

    def load_sample_exceptions(self) -> List[Dict[str, Any]]:
        folder = self.seed_dir / "sample-exception"
        if not folder.exists():
            return []
        return [json.loads(f.read_text()) for f in sorted(folder.glob("*.json"))]

    # -- upsert ----------------------------------------------------------- #

    async def load(self, mongo: MongoClient) -> SeedReport:
        report = SeedReport()

        cap_repo = CapabilityRepository(mongo.collection(CAPABILITIES))
        schema_repo = ArtifactSchemaRepository(mongo.collection(ARTIFACT_SCHEMAS))
        pack_repo = ProcessPackRepository(mongo.collection(PROCESS_PACKS))
        sample_repo = SampleExceptionRepository(mongo.collection(SAMPLE_EXCEPTIONS))

        # 1) artifact schemas
        for reg in self.load_artifact_schemas():
            label = f"artifact-schema {reg.artifact_key}@{reg.version}"
            existing = await schema_repo.get_raw(reg.artifact_key, reg.version)
            if existing is None:
                await schema_repo.insert(reg)
                report.inserted.append(label)
            elif _strip(existing) == _strip(reg.to_doc()):
                report.skipped.append(label)
            else:
                raise SeedConflictError(f"{label} changed but version is immutable")

        # 2) capabilities
        for cap in self.load_capabilities():
            label = f"capability {cap.capability_id}@{cap.version}"
            existing = await cap_repo.get_raw(cap.capability_id, cap.version)
            if existing is None:
                await cap_repo.insert(cap)
                report.inserted.append(label)
            elif _strip(existing) == _strip(cap.to_doc()):
                report.skipped.append(label)
            else:
                raise SeedConflictError(f"{label} changed but version is immutable")

        # 3) process pack (+ bpmn)
        manifest, bpmn_xml = self.load_manifest()
        label = f"pack {manifest.pack_key}@{manifest.version}"
        existing = await pack_repo.get_raw(manifest.pack_key, manifest.version)
        if existing is None:
            await pack_repo.insert(manifest, bpmn_xml)
            report.inserted.append(label)
        elif _strip(existing) == _strip(manifest.to_doc()) and existing.get("bpmn_xml") == bpmn_xml:
            report.skipped.append(label)
        else:
            raise SeedConflictError(f"{label} changed but version is immutable")

        # 4) sample exceptions (seed-only, upserted as-is)
        for sample in self.load_sample_exceptions():
            await sample_repo.upsert(sample)
            report.inserted.append(f"sample-exception {sample['exception_id']}")

        logger.info("Seed complete: %s", report.as_dict())
        return report


async def _main() -> None:
    from app.config import settings
    from app.logging_conf import configure_logging

    configure_logging(settings.LOG_LEVEL)
    mongo = MongoClient(settings.MONGO_URI, settings.MONGO_DB)
    await mongo.connect()
    try:
        report = await SeedLoader(settings.SEED_DIR).load(mongo)
        print(json.dumps(report.as_dict(), indent=2))
    finally:
        await mongo.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
