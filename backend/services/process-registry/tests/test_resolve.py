# tests/test_resolve.py
from app.db.mongo import PROCESS_PACKS
from app.services.resolver import ResolveService
from tests.conftest import load_sample

WIRE_WHEN = {"all": [
    {"field": "exception_type", "op": "eq", "value": "unable_to_apply"},
    {"field": "payment.msg_type", "op": "starts_with", "value": "pacs.008"},
    {"field": "reason_codes", "op": "intersects", "value": ["AC01", "AC04", "RC01", "BE04"]},
]}
ENV = {"exception_type": "unable_to_apply", "payment": {"msg_type": "pacs.008.001.10"},
       "reason_codes": ["AC01"]}


def _active_pack(pack_key, version, *, priority, rule_id, tenant_scope="global", when=WIRE_WHEN):
    return {
        "pack_key": pack_key, "version": version, "status": "active",
        "tenant_scope": tenant_scope,
        "triage_rules": [{"rule_id": rule_id, "priority": priority, "when": when}],
    }


async def test_resolve_api_returns_seed_pack(client, onboarded):
    resp = await client.post("/resolve", json={"tenant": "bank-alpha", "envelope": load_sample()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["pack_key"] == "wire-repair-standard"
    assert body["pack_version"] == "1.0.0"
    assert body["rule_id"] == "wire-uta-repairable-codes"


async def test_resolve_no_match_404(client, onboarded):
    resp = await client.post("/resolve", json={"tenant": "bank-alpha",
                                               "envelope": {"exception_type": "returned"}})
    assert resp.status_code == 404
    body = resp.json()
    assert body["considered_packs"] >= 1 and body["tenant"] == "bank-alpha"


async def test_priority_ordering(db, resolver):
    await db[PROCESS_PACKS].insert_one(_active_pack("pack-low", "1.0.0", priority=100, rule_id="r-low"))
    await db[PROCESS_PACKS].insert_one(_active_pack("pack-high", "1.0.0", priority=50, rule_id="r-high"))
    result, considered = await resolver.resolve("bank-alpha", ENV)
    assert considered == 2
    assert result.pack_key == "pack-high"  # lower priority number wins


async def test_tiebreak_pack_key_then_version_desc(db, resolver):
    await db[PROCESS_PACKS].insert_one(_active_pack("bpack", "1.0.0", priority=10, rule_id="r1"))
    await db[PROCESS_PACKS].insert_one(_active_pack("apack", "1.0.0", priority=10, rule_id="r2"))
    await db[PROCESS_PACKS].insert_one(_active_pack("apack", "2.0.0", priority=10, rule_id="r3"))
    result, _ = await resolver.resolve("bank-alpha", ENV)
    assert result.pack_key == "apack" and result.pack_version == "2.0.0"  # pack_key asc, version desc


async def test_tenant_scope_filtering(db, resolver):
    await db[PROCESS_PACKS].insert_one(
        _active_pack("beta-only", "1.0.0", priority=1, rule_id="rb", tenant_scope=["bank-beta"]))
    result, considered = await resolver.resolve("bank-alpha", ENV)
    assert result is None and considered == 0  # out of scope for bank-alpha


async def test_deterministic(db, resolver):
    await db[PROCESS_PACKS].insert_one(_active_pack("p1", "1.0.0", priority=5, rule_id="r1"))
    await db[PROCESS_PACKS].insert_one(_active_pack("p2", "1.0.0", priority=5, rule_id="r2"))
    first = (await resolver.resolve("bank-alpha", ENV))[0]
    resolver.invalidate()
    second = (await resolver.resolve("bank-alpha", ENV))[0]
    assert (first.pack_key, first.rule_id) == (second.pack_key, second.rule_id)
