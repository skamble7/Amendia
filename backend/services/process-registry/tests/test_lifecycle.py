# tests/test_lifecycle.py
from tests.conftest import load_bpmn, load_manifest

PK, PV = "wire-repair-standard", "1.0.0"
XML_HEADERS = {"content-type": "application/xml"}


async def test_activation_pins_parallel_profile_from_bpmn(cap_repo, schema_repo):
    # ADR-027 Phase 2.5: activation derives the min execution profile FROM the BPMN and pins it into
    # the resolution sidecar — this is exactly the parse → required_profile → resolve_pins chain that
    # packs.activate_pack / onboarding.commit run. A diagram with parallel gateways pins "parallel".
    from amendia_bpmn import parse, required_profile
    from app.services.activation import resolve_pins

    manifest = load_manifest()
    pid = manifest.process.process_id
    parallel_xml = (
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
        f'<bpmn:process id="{pid}" isExecutable="true">'
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:parallelGateway id="Fork"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>fa</bpmn:outgoing><bpmn:outgoing>fb</bpmn:outgoing></bpmn:parallelGateway>'
        '<bpmn:serviceTask id="A"><bpmn:incoming>fa</bpmn:incoming><bpmn:outgoing>aj</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:serviceTask id="B"><bpmn:incoming>fb</bpmn:incoming><bpmn:outgoing>bj</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:parallelGateway id="Join"><bpmn:incoming>aj</bpmn:incoming><bpmn:incoming>bj</bpmn:incoming><bpmn:outgoing>je</bpmn:outgoing></bpmn:parallelGateway>'
        '<bpmn:endEvent id="E"><bpmn:incoming>je</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Fork"/>'
        '<bpmn:sequenceFlow id="fa" sourceRef="Fork" targetRef="A"/>'
        '<bpmn:sequenceFlow id="fb" sourceRef="Fork" targetRef="B"/>'
        '<bpmn:sequenceFlow id="aj" sourceRef="A" targetRef="Join"/>'
        '<bpmn:sequenceFlow id="bj" sourceRef="B" targetRef="Join"/>'
        '<bpmn:sequenceFlow id="je" sourceRef="Join" targetRef="E"/>'
        '</bpmn:process></bpmn:definitions>'
    )
    model, _ = parse(parallel_xml, pid, profile="parallel")
    assert required_profile(model) == "common_executable"

    resolution, _ = await resolve_pins(
        manifest, cap_repo, schema_repo, required_execution_profile=required_profile(model))
    assert resolution.required_execution_profile == "common_executable"
    # and the sidecar doc that gets stored carries it (what GET /resolution returns)
    assert resolution.to_doc()["required_execution_profile"] == "common_executable"


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
    # ADR-027 Phase 2.5: the BPMN-derived min execution profile is pinned into the sidecar. The seed
    # has no parallel gateways → common_subset.
    assert resolution["required_execution_profile"] == "common_subset"

    # validation report persisted
    assert (await client.get(f"/packs/{PK}/{PV}/validation-report")).status_code == 200


async def test_validate_report_and_bpmn_endpoints(client, onboarded):
    # onboarded fixture drives the full pipeline to active
    assert (await client.get(f"/packs/{PK}/{PV}")).json()["status"] == "active"
    bpmn = await client.get(f"/packs/{PK}/{PV}/bpmn")
    assert bpmn.headers["content-type"].startswith("application/xml")
    assert "Process_WireRepairStandard" in bpmn.text
