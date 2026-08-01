# tests/test_copilot_trigger.py
"""ADR-052 refinement — a sample-derived trigger schema must be OPEN.

Regression for `dispatch rejected: envelope_invalid`: a copilot-onboarded pack rejected its real trigger event
because trigger.py derived a CLOSED (additionalProperties:false, required:all) schema from a hand-picked sample —
but the real event (a nested pacs.008 wire exception) carries more fields than any sample. A trigger validates the
fields the pack consumes; it must not forbid extras (the authoritative seed `art.payment.wire_exception` is
deliberately open). These tests pin the fix and would fail under the old closed derivation.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from app.services.copilot.trigger import resolve_trigger_schema, schema_from_sample

# The canonical stub-emitted wire exception (a full WireExceptionEnvelope: nested payment + related_messages +
# attachments) — the exact shape the emitter produces and dispatch fetches back.
_REAL_WIRE = json.loads(
    (Path(__file__).resolve().parents[3] / "docs" / "methodology" / "worked-examples" / "wire_transfer"
     / "schemas" / "wire_exception.sample.json").read_text())


def _valid(schema, doc) -> bool:
    return not list(jsonschema.Draft202012Validator(schema).iter_errors(doc))


# The OLD, buggy derivation — closed + everything required — reproduced here so the tests can prove the fix.
def _old_closed_schema(sample):
    def typ(v):
        if isinstance(v, bool): return {"type": "boolean"}
        if isinstance(v, int): return {"type": "integer"}
        if isinstance(v, float): return {"type": "number"}
        if isinstance(v, str): return {"type": "string"}
        if isinstance(v, list): return {"type": "array", "items": typ(v[0]) if v else {"type": "string"}}
        if isinstance(v, dict):
            return {"type": "object", "additionalProperties": False,
                    "properties": {k: typ(x) for k, x in v.items()}, "required": sorted(v)}
        return {"type": "string"}
    return typ(sample)


def test_open_trigger_accepts_a_richer_real_event_that_the_closed_one_rejected():
    # A hand-picked sample carries FEWER fields than the real event (no related_messages / attachments).
    sample = {k: v for k, v in _REAL_WIRE.items() if k not in ("related_messages", "attachments")}
    schema = schema_from_sample(sample)

    # derived schema is OPEN (extras allowed) and NOT over-required
    assert "additionalProperties" not in schema and "required" not in schema
    assert schema["properties"]["payment"].get("additionalProperties") is None   # nested objects open too

    assert _valid(schema, _REAL_WIRE)                       # the real event now PASSES
    assert not _valid(_old_closed_schema(sample), _REAL_WIRE)   # …and WOULD HAVE FAILED under the old closed derivation


def test_open_trigger_accepts_an_event_missing_a_sampled_field():
    # The other failure mode: over-requiring. A later real event omits a field the sample happened to include.
    sample = _REAL_WIRE                                     # sample has `status`
    thinner = {k: v for k, v in _REAL_WIRE.items() if k != "status"}
    assert _valid(schema_from_sample(sample), thinner)     # nothing required → PASSES
    assert not _valid(_old_closed_schema(sample), thinner)  # old `required: [status, ...]` rejected it


def test_pasted_json_schema_additionalProperties_is_respected_never_force_closed():
    # An authored OPEN schema stays open (the default) — the copilot must not force-close it.
    authored_open = {"type": "object", "properties": {"exception_type": {"type": "string"}}}
    assert "additionalProperties" not in resolve_trigger_schema(authored_open)
    # An authored CLOSED schema stays closed — the operator's choice is respected either way.
    authored_closed = {"type": "object", "additionalProperties": False, "properties": {"a": {"type": "string"}}}
    assert resolve_trigger_schema(authored_closed)["additionalProperties"] is False


def test_restaurant_party_seated_still_passes():
    party = {"ticket_id": "T-1", "order_type": "dine_in", "dietary_flags": ["nuts"]}
    schema = schema_from_sample(party)
    assert _valid(schema, party)                                        # the sample itself
    assert _valid(schema, {**party, "table": "5", "party_size": 2})     # a richer real party event, too


@pytest.mark.parametrize("bad", [[], "x", 42, None])
def test_non_object_trigger_is_a_clean_error(bad):
    with pytest.raises(ValueError):
        resolve_trigger_schema(bad)   # type: ignore[arg-type]
