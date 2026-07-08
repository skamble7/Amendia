# tests/test_versioned_ref.py
import pytest
from pydantic import BaseModel, ValidationError

from app.models.common import ArtifactRef, CapabilityRef, VersionedRef


def test_parse_range_and_pin():
    r = CapabilityRef.parse("cap.payment.draft_repair@^1.0.0")
    assert r.ref_id == "cap.payment.draft_repair"
    assert r.spec == "^1.0.0"
    assert r.is_pinned is False
    assert str(r) == "cap.payment.draft_repair@^1.0.0"

    p = ArtifactRef.parse("art.payment.repair_verdict@1.2.3")
    assert p.is_pinned is True


def test_equality_and_hash():
    assert CapabilityRef.parse("cap.x.y@1.0.0") == CapabilityRef.parse("cap.x.y@1.0.0")
    assert len({VersionedRef.parse("a.b@1.0.0"), VersionedRef.parse("a.b@1.0.0")}) == 1


@pytest.mark.parametrize("bad", ["cap.payment.draft_repair", "cap.x@", "@1.0.0", "cap.x@1@2"])
def test_reject_malformed(bad):
    with pytest.raises(ValueError):
        VersionedRef.parse(bad)


def test_prefix_enforced_by_context():
    with pytest.raises(ValueError):
        CapabilityRef.parse("art.payment.x@1.0.0")  # wrong prefix for a capability ref
    with pytest.raises(ValueError):
        ArtifactRef.parse("cap.payment.x@1.0.0")


def test_pydantic_field_roundtrip():
    class M(BaseModel):
        cap: CapabilityRef

    m = M.model_validate({"cap": "cap.payment.x@^1.0.0"})
    assert isinstance(m.cap, CapabilityRef)
    assert m.model_dump()["cap"] == "cap.payment.x@^1.0.0"
    assert m.model_dump_json() == '{"cap":"cap.payment.x@^1.0.0"}'

    with pytest.raises(ValidationError):
        M.model_validate({"cap": "art.payment.x@1.0.0"})
