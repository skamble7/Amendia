# tests/test_semver.py
import pytest

from amendia_contracts.semver import satisfies


@pytest.mark.parametrize("version,spec,expected", [
    # exact pins
    ("1.2.0", "1.2.0", True),
    ("1.2.1", "1.2.0", False),
    ("1.2.0", "=1.2.0", True),
    # caret, major nonzero
    ("1.2.0", "^1.2.0", True),
    ("1.9.9", "^1.2.0", True),
    ("2.0.0", "^1.2.0", False),
    ("1.1.9", "^1.2.0", False),
    # caret-zero: minor nonzero → <0.(minor+1).0
    ("0.2.3", "^0.2.3", True),
    ("0.2.9", "^0.2.3", True),
    ("0.3.0", "^0.2.3", False),
    ("0.2.2", "^0.2.3", False),
    # caret-zero: patch nonzero → <0.0.(patch+1)
    ("0.0.3", "^0.0.3", True),
    ("0.0.4", "^0.0.3", False),
    # bounded comparators
    ("1.5.0", ">=1.0.0 <2.0.0", True),
    ("2.0.0", ">=1.0.0 <2.0.0", False),
    ("1.0.0", ">=1.0.0 <2.0.0", True),
    ("0.9.9", ">=1.0.0 <2.0.0", False),
    ("1.0.0", ">1.0.0", False),
    ("1.0.1", ">1.0.0", True),
    ("2.0.0", "<=2.0.0", True),
    ("2.0.1", "<=2.0.0", False),
])
def test_satisfies(version, spec, expected):
    assert satisfies(version, spec) is expected


@pytest.mark.parametrize("bad", ["1.2", "1.2.x", "abc", "1.2.3.4", ""])
def test_invalid_version_raises(bad):
    with pytest.raises(ValueError):
        satisfies(bad, "^1.0.0")


@pytest.mark.parametrize("bad_spec", ["", "^1.2", ">=1.2"])
def test_invalid_spec_raises(bad_spec):
    with pytest.raises(ValueError):
        satisfies("1.2.3", bad_spec)
