# tests/test_lifecycle.py
from tests.conftest import load_bpmn, load_manifest

PK, PV = "wire-repair-standard", "1.0.0"
XML_HEADERS = {"content-type": "application/xml"}


def _manifest_json():
    return load_manifest().model_dump(mode="json", by_alias=True)


async def test_submit_rejects_preset_pins(client, registered):
    m = _manifest_json()
    m["requires_capabilities"][0]["resolved"] = "cap.payment.enrich_investigation@1.0.0"
    assert (await client.post("/packs", json=m)).status_code == 422


async def test_full_lifecycle(client, registered):
    # submit draft
    assert (await client.post("/packs", json=_manifest_json())).status_code == 201

    # activate before validate → 422
    assert (await client.post(f"/packs/{PK}/{PV}/activate")).status_code == 422

    # upload BPMN, validate → validated
    assert (await client.put(f"/packs/{PK}/{PV}/bpmn", content=load_bpmn(), headers=XML_HEADERS)).status_code == 200
    rep = (await client.post(f"/packs/{PK}/{PV}/validate")).json()
    assert rep["pack_key"] == PK and not [f for f in rep["findings"] if f["severity"] == "error"]
    assert (await client.get(f"/packs/{PK}/{PV}")).json()["status"] == "validated"

    # mutation (re-upload BPMN) drops back to draft
    assert (await client.put(f"/packs/{PK}/{PV}/bpmn", content=load_bpmn(), headers=XML_HEADERS)).status_code == 200
    assert (await client.get(f"/packs/{PK}/{PV}")).json()["status"] == "draft"

    # re-validate → validated, then activate → active with exact pins
    await client.post(f"/packs/{PK}/{PV}/validate")
    activated = (await client.post(f"/packs/{PK}/{PV}/activate")).json()
    assert activated["status"] == "active"
    pins = {rc["resolved"] for rc in activated["requires_capabilities"]}
    assert "cap.payment.sanctions_screen@1.0.0" in pins
    assert all(rc["resolved"] is not None for rc in activated["requires_capabilities"])

    # resolution sub-doc is present and pinned
    resolution = (await client.get(f"/packs/{PK}/{PV}/resolution")).json()
    assert resolution["capabilities"]["cap.payment.apply_repair"] == "1.0.0"
    assert resolution["artifacts"]["art.payment.repair_verdict"] == "1.0.0"

    # validation report persisted
    assert (await client.get(f"/packs/{PK}/{PV}/validation-report")).status_code == 200


async def test_validate_report_and_bpmn_endpoints(client, onboarded):
    # onboarded fixture drives the full pipeline to active
    assert (await client.get(f"/packs/{PK}/{PV}")).json()["status"] == "active"
    bpmn = await client.get(f"/packs/{PK}/{PV}/bpmn")
    assert bpmn.headers["content-type"].startswith("application/xml")
    assert "Process_WireRepairStandard" in bpmn.text
