# tests/test_api.py
from datetime import datetime, timezone

from app.models.ingestion import EventRef


async def _seed(repo, trigger_id, trigger_type="unable_to_apply"):
    await repo.create_received(
        trigger_id=trigger_id,
        trigger_type=trigger_type,
        event=EventRef(
            event_id="evt",
            occurred_at=datetime.now(timezone.utc),
            schema_version="pin.payments.wire_exception/1.0",
            routing_key="trigger_source.trigger_raised.v1",
            fetch_url=f"http://localhost:8081/triggers/{trigger_id}",
        ),
        detail={"exception_id": trigger_id},
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
    assert body["trigger_id"] == "EXC-2026-000001"
    assert body["status"] == "received"
    assert len(body["status_history"]) == 1


async def test_get_unknown_404(client):
    resp = await client.get("/ingestions/EXC-2026-999999")
    assert resp.status_code == 404


async def test_list_filters(client, repo):
    await _seed(repo, "EXC-2026-000001", trigger_type="unable_to_apply")
    await _seed(repo, "EXC-2026-000002", trigger_type="other_type")

    typed = await client.get("/ingestions", params={"trigger_type": "unable_to_apply"})
    assert typed.status_code == 200
    data = typed.json()
    assert len(data) == 1 and data[0]["trigger_id"] == "EXC-2026-000001"

    received = await client.get("/ingestions", params={"status": "received"})
    assert len(received.json()) == 2


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ready"] is True
    assert body["mongo"] is True and body["rabbit"] is True
