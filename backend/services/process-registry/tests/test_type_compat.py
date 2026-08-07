# tests/test_type_compat.py
"""Domain-neutral JSON-Schema type-compatibility guard (ADR-052 follow-up)."""
from app.validation.type_compat import schema_at_path, schema_type_compat

_STR = {"type": "string"}
_NUM = {"type": "number"}
_OBJ = {"type": "object", "properties": {"id": _STR, "scheme": _STR}}
_OPEN = {"type": "object"}                      # open object, no declared props
_ANY = {}                                       # no type at all


# ---- compatible ----------------------------------------------------------- #
def test_exact_scalar_match_compatible():
    assert schema_type_compat(_STR, _STR) == "compatible"

def test_integer_into_number_compatible():
    assert schema_type_compat({"type": "integer"}, _NUM) == "compatible"

def test_anything_into_permissive_target_compatible():
    assert schema_type_compat(_OBJ, _OPEN) == "compatible"
    assert schema_type_compat(_OBJ, _ANY) == "compatible"
    assert schema_type_compat({"type": "array", "items": _OBJ}, _OPEN) == "compatible"

def test_object_into_object_with_matching_declared_props_compatible():
    src = {"type": "object", "properties": {"name": _STR, "account": _STR}}
    tgt = {"type": "object", "properties": {"name": _STR, "account": _STR}}
    assert schema_type_compat(src, tgt) == "compatible"

def test_nullable_union_source_unwrapped():
    src = {"anyOf": [_OBJ, {"type": "null"}]}
    assert schema_type_compat(src, _OPEN) == "compatible"        # object branch → permissive target
    assert schema_type_compat(src, _STR) == "incompatible"       # object branch → string target


# ---- incompatible (the real wire cases) ----------------------------------- #
def test_object_into_string_incompatible():
    # SCREEN_INPUT.party.account = string; trigger payment.creditor.account = object → the wire "Screen" hold.
    assert schema_type_compat(_OBJ, _STR) == "incompatible"

def test_array_of_object_into_array_of_string_incompatible():
    # NOTIFY_INPUT.recipients = array<string>; trigger related_messages = array<object> → the wire "Notify" hold.
    src = {"type": "array", "items": _OBJ}
    tgt = {"type": "array", "items": _STR}
    assert schema_type_compat(src, tgt) == "incompatible"

def test_array_into_string_incompatible():
    assert schema_type_compat({"type": "array", "items": _STR}, _STR) == "incompatible"

def test_scalar_into_object_incompatible():
    assert schema_type_compat(_STR, _OBJ) == "incompatible"

def test_scalar_into_array_incompatible():
    assert schema_type_compat(_STR, {"type": "array", "items": _STR}) == "incompatible"

def test_typed_open_declared_property_mismatch_incompatible():
    # `_typed_open` target: additionalProperties open, but a DECLARED prop (account:string) still binds.
    tgt = {"type": "object", "properties": {"role": _STR, "name": _STR, "account": _STR}}  # not closed
    src = {"type": "object", "properties": {"name": _STR, "account": _OBJ}}                # account is object
    assert schema_type_compat(src, tgt) == "incompatible"


# ---- unknown (degrade gracefully, never a false block) -------------------- #
def test_opaque_source_is_unknown():
    assert schema_type_compat(_ANY, _STR) == "unknown"
    assert schema_type_compat(None, _STR) == "unknown"

def test_ambiguous_union_target_is_unknown():
    assert schema_type_compat(_OBJ, {"anyOf": [_STR, _NUM]}) == "unknown"

def test_missing_target_is_unknown():
    assert schema_type_compat(_STR, None) == "unknown"


# ---- schema_at_path ------------------------------------------------------- #
def test_schema_at_path_navigates_and_unwraps():
    schema = {"type": "object", "properties": {
        "payment": {"type": "object", "properties": {
            "creditor": {"anyOf": [{"type": "object", "properties": {"account": _OBJ}}, {"type": "null"}]}}}}}
    node = schema_at_path(schema, "payment.creditor")
    assert node and node.get("type") == "object"
    assert schema_at_path(schema, "payment.creditor.account").get("type") == "object"
    assert schema_at_path(schema, "payment.missing") is None      # undeclared hop → None (unknown)
    assert schema_at_path(schema, "") == schema                    # empty path → the schema itself
