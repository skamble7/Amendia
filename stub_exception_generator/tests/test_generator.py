# tests/test_generator.py
import hashlib

from app.generator import NARRATIVES, REASON_CODES, generate_envelope
from app.models.api import GenerateRequest
from app.sample_data import CATALOG

BASE_URL = "http://localhost:8081"


def gen(**kwargs):
    return generate_envelope(GenerateRequest(**kwargs), BASE_URL)


def test_overrides_are_honored():
    env = gen(reason_code="AC04", amount=123456.78, currency="EUR",
              include_attachments=True)
    assert env.reason_codes == ["AC04"]
    assert env.payment.settlement_amount.value == 123456.78
    assert env.payment.settlement_amount.currency == "EUR"
    assert len(env.attachments) == 2


def test_randomization_within_allowed_sets():
    for _ in range(200):
        env = gen()
        assert env.reason_codes[0] in REASON_CODES
        assert 10_000 <= env.payment.settlement_amount.value <= 5_000_000
        assert env.exception_type == "unable_to_apply"
        assert env.status == "open"
        assert env.payment.msg_type.startswith("pacs.008")
        assert env.source.system == "payment-hub-sim"
        assert env.source.channel == "swift"


def test_narrative_matches_reason_code():
    for code in REASON_CODES:
        env = gen(reason_code=code)
        assert env.reason_narrative == NARRATIVES[code]


def test_attachment_presence_variation():
    seen_counts = {len(gen(include_attachments=None).attachments) for _ in range(300)}
    # Over many runs we should see none, one, and both.
    assert 0 in seen_counts and 2 in seen_counts
    assert gen(include_attachments=False).attachments == []


def test_sha256_correctness_and_fetch_url_shape():
    env = gen(include_attachments=True)
    for att in env.attachments:
        expected = hashlib.sha256(CATALOG[att.attachment_id].path.read_bytes()).hexdigest()
        assert att.sha256 == expected
        assert len(att.sha256) == 64
        assert att.fetch_url == (
            f"{BASE_URL}/exceptions/{env.exception_id}/attachments/{att.attachment_id}"
        )


def test_exception_id_shape():
    env = gen()
    parts = env.exception_id.split("-")
    assert parts[0] == "EXC"
    assert len(parts[2]) == 6 and parts[2].isdigit()


def test_uetr_is_unique_uuid():
    ids = {gen().payment.uetr for _ in range(50)}
    assert len(ids) == 50
