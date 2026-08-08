# tests/test_pack_ownership_isolation.py
"""ADR-060 acceptance — the pack-ownership isolation invariant.

Onboarding the SAME MCP server (same capability_id / artifact_key + version) into two different packs must
yield two INDEPENDENT owned copies: both inserts succeed (no DuplicateError), each pack's ``list_owned`` sees
only its own row, and a pack-scoped ``get`` for pack A never returns pack B's row. Ownership — not the id —
provides the isolation.
"""
from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from amendia_contracts.capability import CapabilityDescriptor

_A = ("pack-alpha", "1.0.0")
_B = ("pack-beta", "1.0.0")


def _cap(pack_key, pack_version):
    # Identical id + version under two different packs — the ADR-060 "own copy per pack" case.
    return CapabilityDescriptor.model_validate({
        "descriptor_version": "1.0", "pack_key": pack_key, "pack_version": pack_version,
        "capability_id": "cap.payment.screen_party", "version": "1.0.0", "title": "Screen",
        "kind": "mcp", "side_effect": "read_only",
        "inputs": [], "outputs": [],
        "runtime": {"kind": "mcp", "endpoint": "http://mcp.local/mcp", "tools": ["screen_party"]},
        "status": "active",
    })


def _schema(pack_key, pack_version):
    return ArtifactSchemaRegistration.model_validate({
        "pack_key": pack_key, "pack_version": pack_version,
        "artifact_key": "art.payment.wire_exception", "version": "1.0.0", "title": "Wire",
        "json_schema": {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
                        "additionalProperties": False, "properties": {"x": {"type": "string"}}},
        "compatibility": "backward", "status": "active",
    })


async def test_same_capability_under_two_packs_are_independent_copies(cap_repo):
    # both inserts succeed — no cross-pack DuplicateError even though id@version is identical
    await cap_repo.insert(_cap(*_A))
    await cap_repo.insert(_cap(*_B))

    # each pack owns exactly its own row
    owned_a = await cap_repo.list_owned(*_A)
    owned_b = await cap_repo.list_owned(*_B)
    assert [c.pack_key for c in owned_a] == ["pack-alpha"]
    assert [c.pack_key for c in owned_b] == ["pack-beta"]

    # a pack-scoped get returns only that pack's copy (never the other pack's)
    got_a = await cap_repo.get(*_A, "cap.payment.screen_party", "1.0.0")
    got_b = await cap_repo.get(*_B, "cap.payment.screen_party", "1.0.0")
    assert got_a is not None and got_a.pack_key == "pack-alpha"
    assert got_b is not None and got_b.pack_key == "pack-beta"

    # list_by_id is likewise scoped — pack A never sees pack B's row
    by_id_a = await cap_repo.list_by_id(*_A, "cap.payment.screen_party")
    assert {c.pack_key for c in by_id_a} == {"pack-alpha"}


async def test_same_schema_under_two_packs_are_independent_copies(schema_repo):
    await schema_repo.insert(_schema(*_A))
    await schema_repo.insert(_schema(*_B))

    owned_a = await schema_repo.list_owned(*_A)
    owned_b = await schema_repo.list_owned(*_B)
    assert [s.pack_key for s in owned_a] == ["pack-alpha"]
    assert [s.pack_key for s in owned_b] == ["pack-beta"]

    got_a = await schema_repo.get(*_A, "art.payment.wire_exception", "1.0.0")
    got_b = await schema_repo.get(*_B, "art.payment.wire_exception", "1.0.0")
    assert got_a is not None and got_a.pack_key == "pack-alpha"
    assert got_b is not None and got_b.pack_key == "pack-beta"

    by_key_a = await schema_repo.list_by_key(*_A, "art.payment.wire_exception")
    assert {s.pack_key for s in by_key_a} == {"pack-alpha"}
