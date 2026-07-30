# tests/test_dining_api.py — the POST /tickets/generate endpoint (mirrors test_api.py's generate tests).


async def test_generate_ticket_201_and_publishes(client, publisher):
    resp = await client.post("/tickets/generate", json={"count": 2})
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["created"]) == 2
    for item in body["created"]:
        assert item["published"] is True
        assert item["warning"] is None
        assert item["routing_key"] == "stub_exception.exception_raised.v1"
        assert item["ticket"]["order_type"] == "dine_in"
        assert item["ticket"]["schema_version"] == "pin.dining.party_seated/1.0"
    assert len(publisher.published) == 2


async def test_empty_body_defaults_to_one_clean_ticket(client):
    resp = await client.post("/tickets/generate")
    assert resp.status_code == 201
    created = resp.json()["created"]
    assert len(created) == 1
    t = created[0]["ticket"]
    # The slim trigger carries no food order and no tender; a clean party has no dietary flags.
    assert t["dietary_flags"] == []
    assert "requested_items" not in t
    assert "tender" not in t


async def test_with_nut_allergy_flags_the_party_at_seating(client):
    resp = await client.post("/tickets/generate", json={"with_nut_allergy": True})
    t = resp.json()["created"][0]["ticket"]
    assert t["dietary_flags"] == ["nuts"]  # party-level allergen → screen_allergens conflict once a nuts item is picked


async def test_count_cap(client):
    assert (await client.post("/tickets/generate", json={"count": 21})).status_code == 422


async def test_fetch_back_returns_the_stored_ticket(client):
    tid = (await client.post("/tickets/generate")).json()["created"][0]["ticket"]["ticket_id"]
    got = await client.get(f"/tickets/{tid}")
    assert got.status_code == 200
    assert got.json()["order_type"] == "dine_in"


async def test_publish_failure_is_surfaced_not_rolled_back(client, publisher):
    publisher.fail = True
    resp = await client.post("/tickets/generate")
    assert resp.status_code == 201
    item = resp.json()["created"][0]
    assert item["published"] is False
    assert "publish failed" in item["warning"]
