# tests/test_repositories.py
import pytest

from app.config import settings
from app.dal.base import DuplicateError
from app.models.process_instance import ProcessInstance
from app.seeding.load import SeedLoader


async def test_duplicate_pack_insert_raises(mongo, pack_repo):
    manifest, bpmn = SeedLoader(settings.SEED_DIR).load_manifest()
    await pack_repo.insert(manifest, bpmn)
    with pytest.raises(DuplicateError):
        await pack_repo.insert(manifest, bpmn)


async def test_duplicate_capability_insert_raises(mongo, capability_repo):
    caps = SeedLoader(settings.SEED_DIR).load_capabilities()
    await capability_repo.insert(caps[0])
    with pytest.raises(DuplicateError):
        await capability_repo.insert(caps[0])


async def test_get_and_latest_active(mongo, capability_repo):
    caps = SeedLoader(settings.SEED_DIR).load_capabilities()
    for c in caps:
        await capability_repo.insert(c)
    got = await capability_repo.get("cap.payment.sanctions_screen", "1.0.0")
    assert got is not None and got.kind.value == "mcp"
    latest = await capability_repo.get_latest_active("cap.payment.sanctions_screen")
    assert latest.version == "1.0.0"


async def test_instance_idempotency_key_unique(mongo, instance_repo):
    inst = ProcessInstance.new(
        process_instance_id="PI-1", tenant="bank-alpha", exception_id="EXC-1",
        pack_key="wire-repair-standard", pack_version="1.0.0",
    )
    await instance_repo.insert(inst)
    dup = ProcessInstance.new(
        process_instance_id="PI-2", tenant="bank-alpha", exception_id="EXC-1",
        pack_key="wire-repair-standard", pack_version="1.0.0",
    )  # same idempotency key
    with pytest.raises(DuplicateError):
        await instance_repo.insert(dup)
    assert inst.idempotency_key == "bank-alpha:EXC-1:wire-repair-standard:1.0.0"


async def test_list_filters(mongo, capability_repo):
    for c in SeedLoader(settings.SEED_DIR).load_capabilities():
        await capability_repo.insert(c)
    mcp = await capability_repo.list(kind="mcp")
    assert len(mcp) == 1 and mcp[0].capability_id == "cap.payment.sanctions_screen"
    llm = await capability_repo.list(kind="llm")
    assert {c.capability_id for c in llm} == {
        "cap.payment.draft_rfi", "cap.payment.draft_repair",
        "cap.payment.record_resolution", "cap.payment.draft_return",
    }
