# tests/test_submit_ingress.py
"""ADR-063 cohort worked example — the generic POST /triggers ingress: an external producer injects an
already-built envelope; it persists + publishes a TriggerRaisedEvent, domain-blind (opaque payload)."""
from __future__ import annotations

from amendia_common.events import TRIGGER_RAISED, Service, rk

RAISED_RK = rk(Service.TRIGGER_SOURCE, TRIGGER_RAISED)


async def test_submit_persists_and_publishes_with_correct_fetch_url(client, repo, publisher):
    body = {
        "trigger_type": "ach.assess_exposure_requested",
        "schema_version": "pin.ach.assess_exposure/1.0",
        "source": "pega",
        "payload": {"request_type": "AssessExposureRequested", "case_id": "case-1", "company": "ACME"},
    }
    resp = await client.post("/triggers", json=body)
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["published"] is True and out["routing_key"] == RAISED_RK
    tid = out["trigger"]["trigger_id"]

    # persisted, domain-blind (payload stored opaquely, retrievable via fetch-back)
    stored = repo.store[tid]
    assert stored.trigger_type == "ach.assess_exposure_requested"
    assert stored.payload["case_id"] == "case-1"
    fetched = await client.get(f"/triggers/{tid}")
    assert fetched.status_code == 200 and fetched.json()["case_id"] == "case-1"

    # published event carries the store's own fetch_url (path is what the ingestor uses)
    assert len(publisher.published) == 1
    routing_key, _mid, event = publisher.published[0]
    assert routing_key == RAISED_RK
    assert event["trigger_type"] == "ach.assess_exposure_requested"
    assert event["fetch_url"].endswith(f"/triggers/{tid}")


async def test_submit_is_domain_blind_opaque_payload(client, repo):
    # No domain knowledge: any trigger_type + arbitrary payload is accepted and stored as-is.
    body = {"trigger_type": "anything.at.all", "schema_version": "v1", "payload": {"x": [1, 2], "y": {"z": True}}}
    resp = await client.post("/triggers", json=body)
    assert resp.status_code == 201
    tid = resp.json()["trigger"]["trigger_id"]
    assert repo.store[tid].payload == {"x": [1, 2], "y": {"z": True}}
    assert repo.store[tid].source == "external"  # default source


async def test_submit_requires_payload_and_type(client):
    assert (await client.post("/triggers", json={"schema_version": "v1", "payload": {}})).status_code == 422
    assert (await client.post("/triggers", json={"trigger_type": "t", "schema_version": "v1"})).status_code == 422
