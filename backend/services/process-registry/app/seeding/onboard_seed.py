# app/seeding/onboard_seed.py
"""Onboard the seed dataset through the real registry service layer.

Dependency order: artifact schemas → capabilities → pack manifest → BPMN → validate →
activate. Idempotent (skip already-registered same versions; no-op if the pack is already
active). Doubles as the end-to-end proof of the validator. CLI: ``python -m app.seeding.onboard_seed``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest
from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.bpmn_repo import BpmnRepository
from app.dal.capability_repo import CapabilityRepository
from app.dal.pack_repo import ProcessPackRepository
from app.services.activation import resolve_pins
from app.services.registration import register_schema
from app.validation.bpmn import compute_sha256
from app.validation.pack_validator import PackValidator


def _load_samples(seed: Path) -> List[dict]:
    d = seed / "sample-exception"
    return [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))] if d.exists() else []


async def onboard(
    seed_dir: str | Path,
    cap_repo: CapabilityRepository,
    schema_repo: ArtifactSchemaRepository,
    pack_repo: ProcessPackRepository,
    bpmn_repo: BpmnRepository,
) -> Dict[str, Any]:
    seed = Path(seed_dir)
    report: Dict[str, Any] = {"schemas": [], "capabilities": [], "pack": None, "skipped": []}

    # 1) artifact schemas
    for f in sorted((seed / "artifact-schemas").glob("*.json")):
        reg = ArtifactSchemaRegistration.model_validate_json(f.read_text())
        if await schema_repo.get(reg.artifact_key, reg.version):
            report["skipped"].append(f"schema {reg.artifact_key}@{reg.version}")
            continue
        await register_schema(reg, schema_repo)
        report["schemas"].append(f"{reg.artifact_key}@{reg.version}")

    # 2) capabilities
    for f in sorted((seed / "capabilities").glob("*.json")):
        cap = CapabilityDescriptor.model_validate_json(f.read_text())
        if await cap_repo.get(cap.capability_id, cap.version):
            report["skipped"].append(f"capability {cap.capability_id}@{cap.version}")
            continue
        await cap_repo.insert(cap)
        report["capabilities"].append(f"{cap.capability_id}@{cap.version}")

    # 3) pack manifest (draft)
    manifest = ProcessPackManifest.model_validate_json((seed / "manifest.json").read_text())
    pack_key, version = manifest.pack_key, manifest.version
    existing = await pack_repo.get(pack_key, version)
    if existing is not None and existing.status.value in ("active", "deprecated"):
        report["pack"] = f"{pack_key}@{version} already {existing.status.value} (no-op)"
        return report
    if existing is None:
        await pack_repo.insert(manifest)

    # 4) BPMN upload
    if not await bpmn_repo.get_xml(pack_key, version):
        xml = (seed / manifest.process.bpmn_file).read_text()
        sha = compute_sha256(xml)
        await bpmn_repo.upsert(pack_key, version, xml=xml, sha256=sha)
        await pack_repo.set_bpmn_sha(pack_key, version, sha)

    manifest = await pack_repo.get(pack_key, version)  # reload with current sha/status
    bpmn_xml = await bpmn_repo.get_xml(pack_key, version)

    # 5) validate
    validator = PackValidator(cap_repo, schema_repo)
    vreport = await validator.validate(manifest, bpmn_xml, sample_envelopes=_load_samples(seed))
    await pack_repo.save_validation_report(pack_key, version, vreport.model_dump(mode="json"))
    report["validation"] = {"ok": vreport.ok, "errors": vreport.error_codes(),
                            "findings": len(vreport.findings)}
    if not vreport.ok:
        await pack_repo.set_status(pack_key, version, "draft")
        report["pack"] = f"{pack_key}@{version} FAILED validation"
        return report
    await pack_repo.set_status(pack_key, version, "validated")

    # 6) activate
    resolution, resolved_caps = await resolve_pins(manifest, cap_repo, schema_repo)
    await pack_repo.activate(pack_key, version, resolved_caps=resolved_caps, resolution=resolution.to_doc())
    report["pack"] = f"{pack_key}@{version} ACTIVE (pins: {resolved_caps})"
    return report


async def _main() -> None:
    from app.config import settings
    from app.db.mongo import (
        ARTIFACT_SCHEMAS, BPMN_DOCUMENTS, CAPABILITIES, PROCESS_PACKS, MongoClient,
    )
    from app.logging_conf import configure_logging

    configure_logging(settings.LOG_LEVEL)
    mongo = MongoClient(settings.MONGO_URI, settings.MONGO_DB)
    await mongo.connect()
    try:
        result = await onboard(
            settings.SEED_DIR,
            CapabilityRepository(mongo.collection(CAPABILITIES)),
            ArtifactSchemaRepository(mongo.collection(ARTIFACT_SCHEMAS)),
            ProcessPackRepository(mongo.collection(PROCESS_PACKS)),
            BpmnRepository(mongo.collection(BPMN_DOCUMENTS)),
        )
        print(json.dumps(result, indent=2))
    finally:
        await mongo.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
