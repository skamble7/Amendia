# tests/test_dining_generator.py — mirrors test_generator.py for the dine-in path.
from app.dining_generator import generate_ticket
from app.models.dining_api import GenerateTicketRequest


def gen(**kwargs):
    return generate_ticket(GenerateTicketRequest(**kwargs))


def test_order_type_is_always_dine_in():
    # The triage invariant: whatever else is randomized, order_type must always route to restaurant-dinein.
    for _ in range(200):
        assert gen().order_type == "dine_in"


def test_overrides_are_honored():
    t = gen(table="T9", party_size=4)
    assert t.table == "T9"
    assert t.party_size == 4


def test_happy_path_is_clean():
    # The slim trigger carries no food order and no tender; a clean party has no dietary flags.
    t = gen()
    assert t.dietary_flags == []
    assert t.order_type == "dine_in"


def test_with_nut_allergy_flags_the_party_at_seating():
    t = gen(with_nut_allergy=True)
    assert t.dietary_flags == ["nuts"]  # screen_allergens reads these vs the diner's HITL-selected items


def test_randomization_within_allowed_sets():
    for _ in range(200):
        t = gen()
        assert t.order_type == "dine_in"
        assert 1 <= t.party_size <= 6
        assert t.table in {"T4", "T7", "T12", "T21", "B2", "P1"}
        assert t.dietary_flags == []  # no flag → no allergens at seating


def test_ticket_id_shape():
    parts = gen().ticket_id.split("-")
    assert parts[0] == "TKT"
    assert len(parts[2]) == 6 and parts[2].isdigit()
