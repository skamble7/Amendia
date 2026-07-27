# tests/test_dining_generator.py — mirrors test_generator.py for the dine-in path.
from app.dining_generator import (
    ALLERGEN_ITEM,
    EIGHTY_SIXED_ITEM,
    HAPPY_ITEMS,
    generate_ticket,
)
from app.models.dining_api import GenerateTicketRequest


def gen(**kwargs):
    return generate_ticket(GenerateTicketRequest(**kwargs))


def test_order_type_is_always_dine_in():
    # The triage invariant: whatever else is randomized, order_type must always route to restaurant-dinein.
    for _ in range(200):
        assert gen().order_type == "dine_in"


def test_overrides_are_honored():
    t = gen(table="T9", party_size=4, tender="card")
    assert t.table == "T9"
    assert t.party_size == 4
    assert t.tender == "card"


def test_happy_path_is_clean():
    t = gen()
    assert t.requested_items == HAPPY_ITEMS
    assert EIGHTY_SIXED_ITEM not in t.requested_items
    assert ALLERGEN_ITEM not in t.requested_items
    assert t.tender != "declined"


def test_include_86_item_drives_the_order_revise_loop():
    t = gen(include_86_item=True)
    assert EIGHTY_SIXED_ITEM in t.requested_items
    assert "86" in EIGHTY_SIXED_ITEM  # validate_order treats a name containing "86" as unavailable


def test_allergen_conflict_drives_the_allergen_revise_loop():
    t = gen(allergen_conflict=True)
    assert "nuts" in t.dietary_flags
    assert ALLERGEN_ITEM in t.requested_items  # Peanut Parfait carries the nuts tag → screen_allergens conflict


def test_tender_declined_drives_the_payment_resolve_loop():
    assert gen(tender_declined=True).tender == "declined"


def test_randomization_within_allowed_sets():
    for _ in range(200):
        t = gen()
        assert t.order_type == "dine_in"
        assert 1 <= t.party_size <= 6
        assert t.table in {"T4", "T7", "T12", "T21", "B2", "P1"}
        assert t.tender in {"card", "cash", "mobile"}
        assert t.requested_items == HAPPY_ITEMS  # no flags → the clean order


def test_ticket_id_shape():
    parts = gen().ticket_id.split("-")
    assert parts[0] == "TKT"
    assert len(parts[2]) == 6 and parts[2].isdigit()
