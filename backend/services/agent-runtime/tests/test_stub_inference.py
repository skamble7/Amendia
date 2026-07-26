# tests/test_stub_inference.py
"""ADR-047 D2 — the schema-stub fake for `llm`/`deep_agent` (SIM_CAPABILITIES-free). The generator must
produce a MINIMAL instance that VALIDATES against the pinned output schema — that's all a contract-boundary
host requires; the content is a placeholder.
"""
from jsonschema import Draft202012Validator

from app.engine.executor.stub_inference import stub_from_schema


def _valid(schema, value):
    return not list(Draft202012Validator(schema).iter_errors(value))


def test_scalars_enums_and_const():
    assert stub_from_schema({"type": "string"}) == ""
    assert stub_from_schema({"type": "number"}) == 0
    assert stub_from_schema({"type": "boolean"}) is False
    assert stub_from_schema({"enum": ["a", "b"]}) == "a"
    assert stub_from_schema({"const": 7}) == 7
    assert stub_from_schema({"type": ["string", "null"]}) == ""      # nullable → first non-null


def test_object_only_required_recursively():
    schema = {"type": "object", "required": ["a", "nested"],
              "properties": {"a": {"type": "string"}, "opt": {"type": "number"},
                             "nested": {"type": "object", "required": ["x"],
                                        "properties": {"x": {"type": "boolean"}}}}}
    out = stub_from_schema(schema)
    assert out == {"a": "", "nested": {"x": False}}                  # opt (not required) omitted
    assert _valid(schema, out)


def test_array_minitems_produces_valid_items():
    schema = {"type": "array", "minItems": 2,
              "items": {"type": "object", "required": ["field"], "properties": {"field": {"type": "string"}}}}
    out = stub_from_schema(schema)
    assert out == [{"field": ""}, {"field": ""}] and _valid(schema, out)


def test_stub_validates_against_a_closed_action_ack_shape():
    # e.g. the guideline acknowledgement (closed object, required flags/enum status)
    schema = {"type": "object", "additionalProperties": False,
              "required": ["acknowledged", "action_id", "status"],
              "properties": {"acknowledged": {"type": "boolean"}, "action_id": {"type": "string"},
                             "status": {"type": "string", "enum": ["performed", "queued", "rejected"]}}}
    out = stub_from_schema(schema)
    assert out["status"] == "performed" and _valid(schema, out)
