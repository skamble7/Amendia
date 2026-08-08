# tests/test_cohort_phase2.py
"""ADR-063 Phase 2 — cohort-definition CRUD, membership assignment, and the /resolve close-classification fold."""
from __future__ import annotations

from tests.conftest import load_manifest, load_sample


def _definition(cohort_def_id="wire_transfer_cohort"):
    return {
        "cohort_def_id": cohort_def_id,
        "display_name": "Wire transfer",
        "close_schema": {
            "type": "object",
            "required": ["event", "case_id"],
            "properties": {"event": {"const": "process_ended"}, "case_id": {"type": "string"}},
        },
        "close_correlation_path": "case_id",
        "close_outcome_path": "outcome",
    }


# --- definition CRUD -------------------------------------------------------------------------------

async def test_cohort_definition_crud(client):
    r = await client.post("/cohort/definitions", json=_definition())
    assert r.status_code == 201, r.text
    assert r.json()["cohort_def_id"] == "wire_transfer_cohort"

    assert (await client.post("/cohort/definitions", json=_definition())).status_code == 409  # duplicate

    lst = await client.get("/cohort/definitions")
    assert [d["cohort_def_id"] for d in lst.json()] == ["wire_transfer_cohort"]

    one = await client.get("/cohort/definitions/wire_transfer_cohort")
    assert one.status_code == 200 and one.json()["close_correlation_path"] == "case_id"

    assert (await client.delete("/cohort/definitions/wire_transfer_cohort")).status_code == 204
    assert (await client.get("/cohort/definitions/wire_transfer_cohort")).status_code == 404


async def test_register_rejects_malformed_close_schema(client):
    bad = _definition()
    bad["close_schema"] = {"type": "not-a-real-type"}      # fails JSON-Schema meta-validation
    r = await client.post("/cohort/definitions", json=bad)
    assert r.status_code == 422 and "close_schema" in r.json()["detail"]


# --- membership assignment -------------------------------------------------------------------------

async def test_membership_set_and_clear(client, onboarded):
    await client.post("/cohort/definitions", json=_definition())
    r = await client.put("/packs/wire-repair-standard/1.0.0/cohort-membership",
                         json={"cohort_def_id": "wire_transfer_cohort", "correlation_key": "exception_id"})
    assert r.status_code == 200, r.text
    assert r.json()["cohort_membership"] == {
        "cohort_def_id": "wire_transfer_cohort", "correlation_key": "exception_id"}

    cleared = await client.delete("/packs/wire-repair-standard/1.0.0/cohort-membership")
    assert cleared.status_code == 200 and cleared.json()["cohort_membership"] is None


async def test_membership_unknown_definition_is_422(client, onboarded):
    r = await client.put("/packs/wire-repair-standard/1.0.0/cohort-membership",
                         json={"cohort_def_id": "ghost", "correlation_key": "exception_id"})
    assert r.status_code == 422


async def test_membership_unknown_pack_is_404(client):
    await client.post("/cohort/definitions", json=_definition())
    r = await client.put("/packs/ghost-pack/9.9.9/cohort-membership",
                         json={"cohort_def_id": "wire_transfer_cohort", "correlation_key": "x"})
    assert r.status_code == 404


# --- /resolve fold (close-classification first, back-compat trigger) --------------------------------

async def test_resolve_recognises_close_message(client):
    await client.post("/cohort/definitions", json=_definition())
    r = await client.post("/resolve", json={"envelope": {
        "event": "process_ended", "case_id": "1v23p", "outcome": "settled"}})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "cohort_close"
    assert body["cohort_def_id"] == "wire_transfer_cohort"
    assert body["correlation_value"] == "1v23p"
    assert body["close_outcome"] == "settled"


async def test_resolve_trigger_still_matches_pack_with_kind(client, onboarded):
    r = await client.post("/resolve", json={"envelope": load_sample()})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "trigger"                       # back-compat: existing fields intact + kind added
    assert body["pack_key"] == "wire-repair-standard"


async def test_resolve_no_match_still_404(client, onboarded):
    r = await client.post("/resolve", json={"envelope": {"exception_type": "returned"}})
    assert r.status_code == 404


# --- ADR-063 Phase 3A adjunct: trigger-fields for the membership picker -----------------------------

async def test_trigger_fields_returns_declared_fields(client, onboarded):
    r = await client.get("/packs/wire-repair-standard/1.0.0/trigger-fields")
    assert r.status_code == 200
    fields = r.json()["fields"]
    assert "exception_id" in fields                         # the seed pack's declared trigger field
    assert fields == sorted(fields)                         # stable ordering for the dropdown


async def test_trigger_fields_empty_when_no_declared_trigger(client, pack_repo):
    m = load_manifest().model_dump(mode="json", by_alias=True)
    m["trigger"] = None                                     # a pack that declares no trigger
    m["pack_key"] = "no-trigger-pack"
    from amendia_contracts.process_pack import ProcessPackManifest
    await pack_repo.insert(ProcessPackManifest.model_validate(m))
    r = await client.get("/packs/no-trigger-pack/1.0.0/trigger-fields")
    assert r.status_code == 200 and r.json() == {"fields": []}


async def test_trigger_fields_unknown_pack_404(client):
    assert (await client.get("/packs/ghost/9.9.9/trigger-fields")).status_code == 404


async def test_close_schema_match_without_correlation_value_falls_through(client):
    # A registered close def, but the message satisfies the schema WITHOUT a usable case_id → not a close;
    # falls through to triage → 404 (no pack registered in this test).
    d = _definition()
    d["close_schema"] = {"type": "object", "properties": {"event": {"const": "process_ended"}}}  # case_id optional
    await client.post("/cohort/definitions", json=d)
    r = await client.post("/resolve", json={"envelope": {"event": "process_ended"}})  # no case_id
    assert r.status_code == 404                            # classify returned None → triage → no match
