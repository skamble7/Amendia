# tests/test_ticket_fetchback.py
"""ADR-047 D1: the ticket fetch-back (GET /triggers/{id}) must return the CLEAN domain trigger artifact — only
the ``art.dining.party_seated`` fields — not the persisted row's store metadata. The pack's declared trigger
schema is ``additionalProperties: false``, so the store's ``schema_version`` / ``created_at`` / ``updated_at``
riding along would fail dispatch validation (``reason=envelope_invalid``)."""
from jsonschema import Draft202012Validator

# The pack's declared trigger schema (art.dining.party_seated) — additionalProperties:false over the 6 domain
# fields, mirroring what dispatch validates the fetched artifact against.
_PARTY_SEATED_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["ticket_id", "order_type"],
    "additionalProperties": False,
    "properties": {
        "ticket_id": {"type": "string"},
        "order_type": {"type": "string", "enum": ["dine_in"]},
        "table": {"type": ["string", "null"]},
        "party_size": {"type": ["integer", "null"], "minimum": 1},
        "dietary_flags": {"type": "array", "items": {"type": "string"}},
        "seated_at": {"type": ["string", "null"]},
    },
}

_ENVELOPE_FIELDS = set(_PARTY_SEATED_SCHEMA["properties"])
_STORE_METADATA = {"schema_version", "created_at", "updated_at"}


async def test_fetchback_returns_clean_domain_artifact_not_the_stored_row(client):
    # generate a ticket, then fetch it back the way the ingestor/runtime does.
    gen = await client.post("/generators/dine_in/generate", json={"count": 1})
    assert gen.status_code == 201
    ticket_id = gen.json()["created"][0]["trigger"]["trigger_id"]

    resp = await client.get(f"/triggers/{ticket_id}")
    assert resp.status_code == 200
    payload = resp.json()

    # exactly the 6 domain fields — no store metadata rides along.
    assert set(payload) == _ENVELOPE_FIELDS
    assert not (_STORE_METADATA & set(payload))

    # and it validates against the declared (additionalProperties:false) trigger schema — no envelope_invalid.
    Draft202012Validator(_PARTY_SEATED_SCHEMA).validate(payload)


async def test_fetchback_unknown_ticket_still_404s(client):
    assert (await client.get("/triggers/does-not-exist")).status_code == 404
