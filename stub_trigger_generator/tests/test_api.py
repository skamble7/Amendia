# tests/test_api.py
from httpx import ASGITransport, AsyncClient

from app.deps import get_mongo, get_publisher, get_repo
from app.main import create_app
from tests.conftest import FakeMongo, FakePublisher, FakeRepository

WIRE = "/generators/wire/generate"


async def test_generate_201_and_publishes(client, publisher):
    resp = await client.post(WIRE, json={"count": 2})
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["created"]) == 2
    for item in body["created"]:
        assert item["published"] is True
        assert item["warning"] is None
        assert item["routing_key"] == "trigger_source.trigger_raised.v1"
        assert item["trigger"]["schema_version"] == "pin.payments.wire_exception/1.0"
        assert item["trigger"]["trigger_type"] == "unable_to_apply"
        assert item["trigger"]["source"] == "wire"
        # the whole domain envelope lives under payload (store is domain-blind)
        assert item["trigger"]["payload"]["exception_type"] == "unable_to_apply"
    assert len(publisher.published) == 2


async def test_generate_empty_body_defaults_to_one(client):
    resp = await client.post(WIRE)
    assert resp.status_code == 201
    assert len(resp.json()["created"]) == 1


async def test_generate_respects_count_cap(client):
    resp = await client.post(WIRE, json={"count": 21})
    assert resp.status_code == 422


async def test_unknown_generator_404(client):
    assert (await client.post("/generators/nope/generate")).status_code == 404


async def test_duplicate_trigger_id_returns_409(monkeypatch):
    from app.models.api import GenerateRequest
    from app.generator import generate_envelope as real_gen

    def fixed_gen(req: GenerateRequest, base_url, now=None):
        env = real_gen(req, base_url, now=now)
        env.exception_id = "EXC-2026-000001"  # domain field on the wire envelope
        for att in env.attachments:
            att.fetch_url = f"{base_url}/triggers/EXC-2026-000001/attachments/{att.attachment_id}"
        return env

    monkeypatch.setattr("app.routers.generators.generate_envelope", fixed_gen)

    app = create_app()
    from amendia_auth import AuthContext
    from amendia_auth.settings import AuthSettings
    app.state.auth = AuthContext(AuthSettings(auth_disabled=True, internal_token="test-internal"))
    repo, publisher, mongo = FakeRepository(), FakePublisher(), FakeMongo()
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_publisher] = lambda: publisher
    app.dependency_overrides[get_mongo] = lambda: mongo
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        first = await ac.post(WIRE)
        assert first.status_code == 201
        second = await ac.post(WIRE)
        assert second.status_code == 409
    app.dependency_overrides.clear()


async def test_get_unknown_trigger_404(client):
    resp = await client.get("/triggers/EXC-2026-999999")
    assert resp.status_code == 404


async def test_get_trigger_roundtrip_returns_clean_payload(client):
    created = (await client.post(WIRE)).json()["created"][0]
    tid = created["trigger"]["trigger_id"]
    resp = await client.get(f"/triggers/{tid}")
    assert resp.status_code == 200
    payload = resp.json()
    # fetch-back is the clean domain envelope (no store metadata)
    assert payload["exception_id"] == tid
    assert "schema_version" not in payload and "created_at" not in payload


async def test_attachment_content_types(client):
    created = (await client.post(WIRE, json={"include_attachments": True})).json()["created"][0]
    tid = created["trigger"]["trigger_id"]

    png = await client.get(f"/triggers/{tid}/attachments/att-1")
    assert png.status_code == 200
    assert png.headers["content-type"] == "image/png"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"

    txt = await client.get(f"/triggers/{tid}/attachments/att-2")
    assert txt.status_code == 200
    assert txt.headers["content-type"].startswith("text/plain")


async def test_attachment_unknown_404(client):
    created = (await client.post(WIRE, json={"include_attachments": False})).json()["created"][0]
    tid = created["trigger"]["trigger_id"]
    resp = await client.get(f"/triggers/{tid}/attachments/att-1")
    assert resp.status_code == 404


async def test_list_triggers(client):
    await client.post(WIRE, json={"reason_code": "AC04", "count": 2})
    await client.post(WIRE, json={"reason_code": "AC01", "count": 1})

    all_items = (await client.get("/triggers")).json()
    assert len(all_items) == 3
    assert all(i["trigger_type"] == "unable_to_apply" for i in all_items)
    assert all("reason_codes" in i["payload"] for i in all_items)

    # filter by trigger_type (top-level, domain-blind)
    wire = (await client.get("/triggers", params={"trigger_type": "unable_to_apply"})).json()
    assert len(wire) == 3


async def test_publish_failure_surfaces_warning(monkeypatch):
    app = create_app()
    from amendia_auth import AuthContext
    from amendia_auth.settings import AuthSettings
    app.state.auth = AuthContext(AuthSettings(auth_disabled=True, internal_token="test-internal"))
    repo, publisher, mongo = FakeRepository(), FakePublisher(fail=True), FakeMongo()
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_publisher] = lambda: publisher
    app.dependency_overrides[get_mongo] = lambda: mongo
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(WIRE)
        assert resp.status_code == 201
        item = resp.json()["created"][0]
        assert item["published"] is False
        assert "publish failed" in item["warning"]
        # Insert was kept despite publish failure.
        tid = item["trigger"]["trigger_id"]
        assert (await ac.get(f"/triggers/{tid}")).status_code == 200
    app.dependency_overrides.clear()


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ready"] is True
    assert body["mongo"] is True and body["rabbit"] is True
