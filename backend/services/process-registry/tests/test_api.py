# tests/test_api.py
import json

from tests.conftest import SEED, load_capabilities, load_schemas


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
    cap = _cap_json(load_capabilities()[0])  # a skill
    cap["runtime"] = {"kind": "mcp", "endpoint": "http://x", "tools": ["t"]}
    resp = await client.post("/capabilities", json=cap)
    assert resp.status_code == 422  # model validator: runtime.kind must equal kind


async def test_register_schema_ok_and_convention_errors(client):
    reg = _schema_json(load_schemas()[0])
    assert (await client.post("/artifact-schemas", json=reg)).status_code == 201

    bad = _schema_json(load_schemas()[1])
    bad["json_schema"]["$id"] = "https://evil.example/x.json"
    resp = await client.post("/artifact-schemas", json=bad)
    assert resp.status_code == 422
    assert any("$id" in e for e in resp.json()["detail"]["errors"])


async def test_capabilities_and_schemas_listed(client, registered):
    caps = (await client.get("/capabilities")).json()
    assert len(caps) == 10
    schemas = (await client.get("/artifact-schemas")).json()
    assert len(schemas) == 7
    one = await client.get("/capabilities/cap.payment.sanctions_screen/1.0.0")
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
    r = await client.post("/capabilities/cap.payment.sanctions_screen/1.0.0/deprecate")
    assert r.status_code == 200 and r.json()["status"] == "deprecated"


async def test_unknown_404s(client):
    assert (await client.get("/capabilities/cap.x.y/1.0.0")).status_code == 404
    assert (await client.get("/packs/nope/1.0.0")).status_code == 404


async def test_health(client):
    body = (await client.get("/health")).json()
    assert body["status"] == "ok" and body["mongo"] is True
