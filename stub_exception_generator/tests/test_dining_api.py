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
        assert item["ticket"]["schema_version"] == "pin.dining.order_ticket/1.0"
    assert len(publisher.published) == 2


async def test_empty_body_defaults_to_one_clean_ticket(client):
    resp = await client.post("/tickets/generate")
    assert resp.status_code == 201
    created = resp.json()["created"]
    assert len(created) == 1
    t = created[0]["ticket"]
    assert t["tender"] != "declined"
    assert "Lobster Thermidor (86)" not in t["requested_items"]


async def test_steerable_flags_surface_all_three_loop_drivers(client):
    resp = await client.post(
        "/tickets/generate",
        json={"include_86_item": True, "allergen_conflict": True, "tender_declined": True},
    )
    t = resp.json()["created"][0]["ticket"]
    assert "Lobster Thermidor (86)" in t["requested_items"]           # order-revise
    assert "Peanut Parfait" in t["requested_items"] and "nuts" in t["dietary_flags"]  # allergen-revise
    assert t["tender"] == "declined"                                  # payment-resolve


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
