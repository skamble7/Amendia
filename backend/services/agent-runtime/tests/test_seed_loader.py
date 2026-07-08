# tests/test_seed_loader.py
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from app.config import settings
from app.db.mongo import CAPABILITIES, PROCESS_PACKS
from app.seeding.load import SeedConflictError, SeedLoader


async def test_seed_inserts_then_is_idempotent(mongo, db):
    r1 = await SeedLoader(settings.SEED_DIR).load(mongo)
    # 7 schemas + 10 caps + 1 pack + 1 sample = 19 inserted
    assert len(r1.inserted) == 19
    assert len(r1.skipped) == 0

    r2 = await SeedLoader(settings.SEED_DIR).load(mongo)
    # Re-run: everything already present is skipped (sample is upserted → counts as inserted).
    assert len(r2.skipped) == 18
    assert await db[CAPABILITIES].count_documents({}) == 10
    assert await db[PROCESS_PACKS].count_documents({}) == 1


async def test_sha256_injection_matches_bpmn(mongo, pack_repo):
    await SeedLoader(settings.SEED_DIR).load(mongo)
    manifest = await pack_repo.get("wire-repair-standard", "1.0.0")
    expected = hashlib.sha256((Path(settings.SEED_DIR) / "wire-repair.bpmn").read_bytes()).hexdigest()
    assert manifest.process.bpmn_sha256 == expected


async def test_tamper_same_version_is_refused(mongo, tmp_path):
    seed_copy = tmp_path / "wire-repair-standard"
    shutil.copytree(settings.SEED_DIR, seed_copy)

    await SeedLoader(seed_copy).load(mongo)  # first load OK

    # Change a capability's content without bumping its version.
    cap_file = seed_copy / "capabilities" / "cap.payment.enrich_investigation.json"
    data = json.loads(cap_file.read_text())
    data["title"] = "Tampered title"
    cap_file.write_text(json.dumps(data))

    with pytest.raises(SeedConflictError):
        await SeedLoader(seed_copy).load(mongo)


async def test_bad_embedded_schema_is_rejected(mongo, tmp_path):
    seed_copy = tmp_path / "wire-repair-standard"
    shutil.copytree(settings.SEED_DIR, seed_copy)
    bad = seed_copy / "artifact-schemas" / "art.payment.repair_verdict.json"
    reg = json.loads(bad.read_text())
    reg["json_schema"]["type"] = 12345  # not a valid JSON Schema
    bad.write_text(json.dumps(reg))

    with pytest.raises(Exception):
        await SeedLoader(seed_copy).load(mongo)
