# tests/test_side_effect_waiver.py
"""ADR-065 — the SideEffectWaiver contract: justification is required + substantive, and the field is a purely
additive Optional on Binding (absent ⇒ today's behaviour)."""
import pytest
from pydantic import ValidationError

from amendia_contracts.process_pack import Binding, SideEffectWaiver


def _binding(**over) -> dict:
    d = {"element_id": "T", "element_kind": "serviceTask",
         "executor": {"type": "capability", "capability": "cap.x.notify@^1.0.0"}, "hitl": {"mode": "none"}}
    d.update(over)
    return d


def test_valid_justification_stored_stripped():
    w = SideEffectWaiver(justification="  Idempotent handback to the orchestrator; nothing to gate.  ")
    assert w.justification.startswith("Idempotent") and not w.justification.endswith(" ")


@pytest.mark.parametrize("bad", ["", "   ", "\n\t ", "too short", "under twenty chars"])
def test_short_or_empty_justification_rejected_at_parse_time(bad):
    with pytest.raises(ValidationError):
        SideEffectWaiver(justification=bad)


def test_waiver_has_no_boolean_form():
    with pytest.raises(ValidationError):
        SideEffectWaiver(justification=True)  # not a string / not substantive


def test_binding_waiver_is_additive_optional():
    assert Binding.model_validate(_binding()).side_effect_waiver is None
    b = Binding.model_validate(_binding(
        side_effect_waiver={"justification": "Idempotent handback to the orchestrator; nothing to gate."}))
    assert b.side_effect_waiver.justification.startswith("Idempotent")


def test_binding_waiver_rejects_bad_justification_at_parse_time():
    with pytest.raises(ValidationError):
        Binding.model_validate(_binding(side_effect_waiver={"justification": "short"}))


def test_provenance_fields_are_optional_legacy_waiver_still_parses():
    # ADR-065 P4a: waived_by/waived_at/waived_capability_id are all optional — a pre-P4a waiver (no provenance)
    # must still parse; failing it would break dev sessions and packs created during P1–P3.
    w = SideEffectWaiver(justification="Idempotent handback to the orchestrator; nothing to gate.")
    assert w.waived_by is None and w.waived_at is None and w.waived_capability_id is None


def test_provenance_fields_round_trip_when_present():
    from datetime import datetime, timezone
    w = SideEffectWaiver.model_validate({
        "justification": "Idempotent handback to the orchestrator; nothing to gate.",
        "waived_by": "usr-owner", "waived_at": "2026-09-01T12:00:00Z", "waived_capability_id": "cap.payment.notify"})
    assert w.waived_by == "usr-owner" and w.waived_capability_id == "cap.payment.notify"
    assert w.waived_at == datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
