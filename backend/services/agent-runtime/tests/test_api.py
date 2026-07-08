# tests/test_api.py
import pytest

from app.config import settings
from app.main import create_app


async def test_get_pack_manifest(client, seeded):
    resp = await client.get("/packs/wire-repair-standard/1.0.0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pack_key"] == "wire-repair-standard"
    assert body["version"] == "1.0.0"
    assert len(body["bindings"]) == 12
    assert len(body["process"]["bpmn_sha256"]) == 64
    # `schema` alias is serialized (not `schema_`)
    assert "schema" in body["bindings"][0]["outputs"][0]


async def test_pack_bpmn_content_type(client, seeded):
    resp = await client.get("/packs/wire-repair-standard/1.0.0/bpmn")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert "Process_WireRepairStandard" in resp.text


async def test_list_packs_and_versions(client, seeded):
    assert len(((await client.get("/packs")).json())) == 1
    versions = (await client.get("/packs/wire-repair-standard")).json()
    assert [v["version"] for v in versions] == ["1.0.0"]


async def test_capabilities_and_schemas_retrievable(client, seeded):
    caps = (await client.get("/capabilities")).json()
    assert len(caps) == 10
    schemas = (await client.get("/artifact-schemas")).json()
    assert len(schemas) == 7
    one = await client.get("/capabilities/cap.payment.sanctions_screen/1.0.0")
    assert one.status_code == 200 and one.json()["kind"] == "mcp"
    rv = await client.get("/artifact-schemas/art.payment.repair_verdict/1.0.0")
    assert rv.status_code == 200
    assert "repair_verdict" in rv.json()["json_schema"]["required"]


async def test_capability_kind_filter(client, seeded):
    mcp = (await client.get("/capabilities", params={"kind": "mcp"})).json()
    assert len(mcp) == 1


async def test_unknown_returns_404(client, seeded):
    assert (await client.get("/packs/nope/9.9.9")).status_code == 404
    assert (await client.get("/capabilities/cap.nope.nope/1.0.0")).status_code == 404


async def test_instances_and_tasks_empty(client, seeded):
    assert (await client.get("/instances")).json() == []
    assert (await client.get("/hitl-tasks")).json() == []


async def test_seed_endpoint_runs(client):
    resp = await client.post("/admin/seed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["inserted_count"] >= 18


async def test_health(client, seeded):
    body = (await client.get("/health")).json()
    assert body["status"] == "ok" and body["ready"] is True


async def test_seed_endpoint_flag_off_returns_404(mongo, monkeypatch):
    # Rebuild an app/client with the seed API disabled.
    from httpx import ASGITransport, AsyncClient
    from app.deps import get_mongo

    monkeypatch.setattr(settings, "ENABLE_SEED_API", False)
    app = create_app()
    app.dependency_overrides[get_mongo] = lambda: mongo
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/admin/seed")
    app.dependency_overrides.clear()
    assert resp.status_code == 404
