# tests/test_generators.py
"""The domain-neutral generator catalog: the UI discovers trigger sources here instead of hardcoding domains."""


async def test_generators_lists_both_sources_with_endpoints_and_scenarios(client):
    resp = await client.get("/generators")
    assert resp.status_code == 200
    gens = {g["id"]: g for g in resp.json()["generators"]}
    assert set(gens) == {"wire", "dine_in"}

    for g in gens.values():
        assert g["label"] and g["endpoint"].startswith("/") and g["endpoint"].endswith("/generate")
        assert g["scenarios"], "each generator advertises at least one scenario"
        for s in g["scenarios"]:
            assert s["id"] and s["label"] and isinstance(s["body"], dict)

    # wire scenarios cover the reason codes the triage rule matches; bodies carry the code.
    wire_ids = {s["id"] for s in gens["wire"]["scenarios"]}
    assert {"AC01", "AC04", "RC01", "BE04"} <= wire_ids
    assert all(s["body"].get("reason_code") == s["id"] for s in gens["wire"]["scenarios"])

    # dine-in advertises the happy path + one scenario per demo flag (body {flag: True}).
    dine = {s["id"]: s for s in gens["dine_in"]["scenarios"]}
    assert dine["happy"]["body"] == {}
    assert dine["tender_declined"]["body"] == {"tender_declined": True}


async def test_generator_endpoints_are_actually_callable(client):
    # the advertised endpoints exist and generate — proving the catalog is wired to real routes.
    resp = await client.get("/generators")
    for g in resp.json()["generators"]:
        r = await client.post(g["endpoint"], json=g["scenarios"][0]["body"])
        assert r.status_code == 201, f"{g['endpoint']} not callable"
        assert r.json()["created"], f"{g['endpoint']} produced nothing"
