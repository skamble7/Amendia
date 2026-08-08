# tests/test_api.py
import json

import pytest

from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from app.services.registration import register_schema
from tests.conftest import SEED, load_capabilities, load_schemas


def _authored_reg(json_schema):
    # an operator-authored artifact (art.dining.order) — neither tool I/O nor trigger (ADR-050).
    return ArtifactSchemaRegistration.model_validate({
        "pack_key": "dining-pack", "pack_version": "1.0.0",
        "artifact_key": "art.dining.order", "version": "1.0.0", "title": "Order",
        "json_schema": json_schema, "compatibility": "backward", "status": "active"})


_CANON_ORDER_ID = "https://amendia.dev/schemas/artifacts/dining/order/1.0.0.json"


@pytest.mark.parametrize("supplied_id", ["https://evil.example/x.json", None])
async def test_authored_artifact_id_is_derived_not_validated(schema_repo, supplied_id):
    # ADR-052 E2: declaring an artifact with a foreign-domain $id (or none) registers clean; the stored $id is
    # the canonical URL derived from the artifact key + version.
    js = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
          "additionalProperties": False, "required": ["order_type"],
          "properties": {"order_type": {"type": "string"}}}
    if supplied_id is not None:
        js["$id"] = supplied_id
    stored = await register_schema(_authored_reg(js), schema_repo)
    assert stored.json_schema["$id"] == _CANON_ORDER_ID
    fetched = await schema_repo.get("dining-pack", "1.0.0", "art.dining.order", "1.0.0")
    assert fetched is not None and fetched.json_schema["$id"] == _CANON_ORDER_ID


def _cap_json(cap):
    return cap.model_dump(mode="json", by_alias=True)


def _schema_json(reg):
    return reg.model_dump(mode="json", by_alias=True)


async def test_register_capability_and_409(client):
    cap = load_capabilities()[0]
    r1 = await client.post("/capabilities", json=_cap_json(cap))
    assert r1.status_code == 201
    r2 = await client.post("/capabilities", json=_cap_json(cap))
    assert r2.status_code == 409


async def test_register_capability_runtime_kind_mismatch_422(client):
    # an llm cap whose runtime is overridden to mcp → runtime.kind != top-level kind (ADR-047 D2: the
    # flipped seed has no skill caps, so select an llm one explicitly rather than by list position).
    llm_cap = next(c for c in load_capabilities()
                   if (c.kind.value if hasattr(c.kind, "value") else c.kind) == "llm")
    cap = _cap_json(llm_cap)
    cap["runtime"] = {"kind": "mcp", "endpoint": "http://x", "tools": ["t"]}
    resp = await client.post("/capabilities", json=cap)
    assert resp.status_code == 422  # model validator: runtime.kind must equal kind


async def test_register_schema_ok_and_convention_errors(client):
    reg = _schema_json(load_schemas()[0])
    assert (await client.post("/artifact-schemas", json=reg)).status_code == 201

    # ADR-052 E2: a foreign (or absent) $id is NORMALIZED to the canonical URL, not rejected.
    reg2 = _schema_json(load_schemas()[1])
    reg2["json_schema"]["$id"] = "https://evil.example/x.json"
    resp = await client.post("/artifact-schemas", json=reg2)
    assert resp.status_code == 201, resp.text
    key, ver = reg2["artifact_key"], reg2["version"]
    pk, pv = reg2["pack_key"], reg2["pack_version"]
    _, domain, name = key.split(".", 2)
    stored = (await client.get(f"/packs/{pk}/{pv}/artifact-schemas/{key}/{ver}")).json()
    assert stored["json_schema"]["$id"] == f"https://amendia.dev/schemas/artifacts/{domain}/{name}/{ver}.json"

    # other schema validation still applies — a non-object root is rejected.
    reg3 = _schema_json(load_schemas()[2])
    reg3["json_schema"]["type"] = "string"
    resp3 = await client.post("/artifact-schemas", json=reg3)
    assert resp3.status_code == 422
    assert any("object" in e for e in resp3.json()["detail"]["errors"])


async def test_capabilities_and_schemas_listed(client, registered):
    caps = (await client.get("/capabilities")).json()
    assert len(caps) == 10
    schemas = (await client.get("/artifact-schemas")).json()
    assert len(schemas) == 9  # ADR-047 D2: + art.payment.info_resolution (needs-info human exit)
    one = await client.get(
        "/packs/wire-repair-standard/1.0.0/capabilities/cap.payment.sanctions_screen/1.0.0")
    assert one.status_code == 200 and one.json()["kind"] == "mcp"


async def test_capabilities_free_text_search(client, registered):
    # `q` is a case-insensitive substring over capability_id (+ title) — the on-demand reuse search.
    all_caps = (await client.get("/capabilities")).json()
    screen = (await client.get("/capabilities", params={"q": "SCREEN"})).json()   # case-insensitive
    assert screen and all("screen" in c["capability_id"].lower() or "screen" in (c.get("title") or "").lower()
                          for c in screen)
    assert len(screen) < len(all_caps)                                            # actually narrows
    assert (await client.get("/capabilities", params={"q": "no_such_capability_xyz"})).json() == []


async def test_deprecate_capability(client, registered):
    r = await client.post(
        "/packs/wire-repair-standard/1.0.0/capabilities/cap.payment.sanctions_screen/1.0.0/deprecate")
    assert r.status_code == 200 and r.json()["status"] == "deprecated"


async def test_unknown_404s(client):
    assert (await client.get(
        "/packs/wire-repair-standard/1.0.0/capabilities/cap.x.y/1.0.0")).status_code == 404
    assert (await client.get("/packs/nope/1.0.0")).status_code == 404


async def test_health(client):
    body = (await client.get("/health")).json()
    assert body["status"] == "ok" and body["mongo"] is True
