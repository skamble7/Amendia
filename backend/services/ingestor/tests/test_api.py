# tests/test_api.py
from datetime import datetime, timezone

from app.models.ingestion import EventRef


async def _seed(repo, exception_id, tenant="bank-alpha", exception_type="unable_to_apply"):
    await repo.create_received(
        exception_id=exception_id,
        tenant=tenant,
        exception_type=exception_type,
        event=EventRef(
            event_id="evt",
            occurred_at=datetime.now(timezone.utc),
            schema_version="pin.payments.wire_exception/1.0",
            routing_key=f"{tenant}.stub_exception.exception_raised.v1",
            fetch_url=f"http://localhost:8081/exceptions/{exception_id}",
        ),
        detail={"exception_id": exception_id},
    )


async def test_list_empty(client):
    resp = await client.get("/ingestions")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_and_get(client, repo):
    await _seed(repo, "EXC-2026-000001")
    await _seed(repo, "EXC-2026-000002")

    listed = await client.get("/ingestions")
    assert listed.status_code == 200
    assert len(listed.json()) == 2

    one = await client.get("/ingestions/EXC-2026-000001")
    assert one.status_code == 200
    body = one.json()
    assert body["exception_id"] == "EXC-2026-000001"
    assert body["status"] == "received"
    assert len(body["status_history"]) == 1


async def test_get_unknown_404(client):
    resp = await client.get("/ingestions/EXC-2026-999999")
    assert resp.status_code == 404


async def test_list_filters(client, repo):
    await _seed(repo, "EXC-2026-000001", tenant="acme")
    await _seed(repo, "EXC-2026-000002", tenant="other")

    acme = await client.get("/ingestions", params={"tenant": "acme"})
    assert acme.status_code == 200
    data = acme.json()
    assert len(data) == 1 and data[0]["tenant"] == "acme"

    received = await client.get("/ingestions", params={"status": "received"})
    assert len(received.json()) == 2


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ready"] is True
    assert body["mongo"] is True and body["rabbit"] is True
