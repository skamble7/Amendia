# tests/test_compat.py
from app.validation.compat import diff_schemas, has_breaking


def _obj(props, required=None, extra=None):
    s = {"type": "object", "additionalProperties": False, "properties": props}
    if required is not None:
        s["required"] = required
    if extra:
        s.update(extra)
    return s


def test_new_optional_property_is_non_breaking():
    old = _obj({"a": {"type": "string"}}, ["a"])
    new = _obj({"a": {"type": "string"}, "b": {"type": "string"}}, ["a"])
    f = diff_schemas(old, new)
    assert not has_breaking(f)
    assert any(x.code == "optional_property_added" for x in f)


def test_removed_property_is_breaking():
    old = _obj({"a": {"type": "string"}, "b": {"type": "string"}}, ["a"])
    new = _obj({"a": {"type": "string"}}, ["a"])
    f = diff_schemas(old, new)
    assert has_breaking(f)
    assert any(x.code == "property_removed" and x.path == "/properties/b" for x in f)


def test_new_required_is_breaking():
    old = _obj({"a": {"type": "string"}}, ["a"])
    new = _obj({"a": {"type": "string"}, "b": {"type": "string"}}, ["a", "b"])
    f = diff_schemas(old, new)
    assert has_breaking(f)
    assert any(x.code in ("required_added", "required_property_added") for x in f)


def test_type_narrowed_is_breaking():
    old = _obj({"a": {"type": ["string", "null"]}}, ["a"])
    new = _obj({"a": {"type": "string"}}, ["a"])
    f = diff_schemas(old, new)
    assert has_breaking(f)
    assert any(x.code == "type_narrowed" for x in f)


def test_enum_removed_breaking_added_nonbreaking():
    old = _obj({"a": {"enum": ["x", "y"]}}, ["a"])
    new = _obj({"a": {"enum": ["x", "y", "z"]}}, ["a"])
    assert not has_breaking(diff_schemas(old, new))
    f2 = diff_schemas(new, old)  # z removed
    assert has_breaking(f2)
    assert any(x.code == "enum_values_removed" for x in f2)


def test_additional_properties_tighten_breaking_loosen_nonbreaking():
    open_s = _obj({"a": {"type": "string"}}, ["a"], extra={"additionalProperties": True})
    closed_s = _obj({"a": {"type": "string"}}, ["a"])
    assert has_breaking(diff_schemas(open_s, closed_s))       # true→false breaking
    assert not has_breaking(diff_schemas(closed_s, open_s))   # false→true non-breaking


def test_nested_recursion():
    old = _obj({"inner": _obj({"x": {"type": "string"}}, ["x"])}, ["inner"])
    new = _obj({"inner": _obj({}, [])}, ["inner"])  # inner.x removed
    f = diff_schemas(old, new)
    assert has_breaking(f)
    assert any(x.path == "/properties/inner/properties/x" for x in f)
