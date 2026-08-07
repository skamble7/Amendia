# tests/test_dining_api.py — the POST /generators/dine_in/generate endpoint (ADR-059).

DINE = "/generators/dine_in/generate"


async def test_generate_ticket_201_and_publishes(client, publisher):
    resp = await client.post(DINE, json={"count": 2})
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["created"]) == 2
    for item in body["created"]:
        assert item["published"] is True
        assert item["warning"] is None
        assert item["routing_key"] == "trigger_source.trigger_raised.v1"
        assert item["trigger"]["trigger_type"] == "dine_in"
        assert item["trigger"]["source"] == "dine_in"
        assert item["trigger"]["schema_version"] == "pin.dining.party_seated/1.0"
        assert item["trigger"]["payload"]["order_type"] == "dine_in"
    assert len(publisher.published) == 2


async def test_empty_body_defaults_to_one_clean_ticket(client):
    resp = await client.post(DINE)
    assert resp.status_code == 201
    created = resp.json()["created"]
    assert len(created) == 1
    payload = created[0]["trigger"]["payload"]
    # The slim trigger carries no food order and no tender; a clean party has no dietary flags.
    assert payload["dietary_flags"] == []
    assert "requested_items" not in payload
    assert "tender" not in payload


async def test_with_nut_allergy_flags_the_party_at_seating(client):
    resp = await client.post(DINE, json={"with_nut_allergy": True})
    payload = resp.json()["created"][0]["trigger"]["payload"]
    assert payload["dietary_flags"] == ["nuts"]  # party-level allergen → screen_allergens conflict


async def test_count_cap(client):
    assert (await client.post(DINE, json={"count": 21})).status_code == 422


async def test_fetch_back_returns_clean_domain_payload(client):
    tid = (await client.post(DINE)).json()["created"][0]["trigger"]["trigger_id"]
    got = await client.get(f"/triggers/{tid}")
    assert got.status_code == 200
    assert got.json()["order_type"] == "dine_in"


async def test_publish_failure_is_surfaced_not_rolled_back(client, publisher):
    publisher.fail = True
    resp = await client.post(DINE)
    assert resp.status_code == 201
    item = resp.json()["created"][0]
    assert item["published"] is False
    assert "publish failed" in item["warning"]
