# test_server.py
"""Contract + behaviour tests for the restaurant dine-in MCP server.

These run without the ``mcp`` SDK: they exercise the schemas, handlers, and the import-time
compliance self-check directly (``server.py`` is the only place the SDK is imported).
"""
from __future__ import annotations

import jsonschema
import pytest

from restaurant_dinein_mcp import handlers as H
from restaurant_dinein_mcp import schemas as S


# --------------------------------------------------------------------------- #
# Compliance / contract
# --------------------------------------------------------------------------- #

def test_compliance_self_check_passes():
    H.check_compliance()  # raises AssertionError on any drift


# ADR-057: an input field a HUMAN authors/reviews must declare its `properties` (an opaque `{type:object}` degrades
# the derived HITL form to a raw editor), while staying tolerant (no additionalProperties:false) of a whole artifact.
HUMAN_ARTIFACT_INPUT_FIELDS = {
    "screen_allergens": "party",
    "charge_payment": "bill",
}


def test_human_artifact_input_fields_declare_their_properties():
    for tool, field in HUMAN_ARTIFACT_INPUT_FIELDS.items():
        prop = H.TOOLS_BY_NAME[tool]["input_schema"]["properties"][field]
        assert prop["type"] == "object"
        assert prop.get("properties"), f"{tool}.{field} is an opaque object — declare its properties (ADR-057)"
        assert prop.get("additionalProperties") is not False


def test_exactly_six_tools():
    assert len(H.TOOLS) == 6
    assert set(H.TOOLS_BY_NAME) == {
        "get_menu", "validate_order", "screen_allergens", "generate_bill",
        "fire_ticket", "charge_payment",
    }


@pytest.mark.parametrize("tool", H.TOOLS, ids=lambda t: t["name"])
def test_output_schema_is_closed_object(tool):
    out = tool["output_schema"]
    assert out["type"] == "object"
    for obj in H._iter_objects(out):
        assert obj.get("additionalProperties") is False


@pytest.mark.parametrize("tool", H.TOOLS, ids=lambda t: t["name"])
def test_handler_output_validates_against_output_schema(tool):
    # A representative call for each tool, then validate the structured output against the contract.
    sample_order = {"items": ["Spaghetti alla Carbonara", "Sorbetto al Limone"]}
    args = {
        "ticket_id": "TKT-1",
        "order": sample_order,
        "dietary_flags": ["nuts"],
        "party": {"dietary_flags": ["nuts"]},
        "bill": {"total": 42.0},
        "amount": 42.0,
    }
    result = tool["handler"](args)
    jsonschema.validate(result, tool["output_schema"])


# --------------------------------------------------------------------------- #
# Gateway fields present + required
# --------------------------------------------------------------------------- #

def test_validate_order_verdict_field():
    assert "order_verdict" in S.VALIDATE_ORDER_OUTPUT["required"]
    ok = H.validate_order({"ticket_id": "T", "order": {"items": ["Bruschetta al Pomodoro", "Risotto ai Funghi"]}})
    assert ok["order_verdict"] == "ok"


def test_validate_order_needs_info_on_86_item():
    # "Osso Buco (86)" resolves to available:false in the menu (its name also carries the 86 marker).
    r = H.validate_order({"ticket_id": "T", "order": {"items": ["Osso Buco (86)"]}})
    assert r["order_verdict"] == "needs_info"
    assert "Osso Buco (86)" in r["unavailable_items"]


def test_validate_order_hint_forces_needs_info():
    # The steering hint overrides an otherwise-available order (drives the revise loop in the demo).
    r = H.validate_order({"ticket_id": "T", "order": {"items": ["Bruschetta al Pomodoro"]}, "hint": "needs_info"})
    assert r["order_verdict"] == "needs_info"


def test_screen_allergens_conflict_on_flag_intersection():
    # dietary_flags passes top-level from the trigger; the nuts-tagged Torta di Nocciole conflicts.
    r = H.screen_allergens({
        "ticket_id": "T",
        "dietary_flags": ["nuts"],
        "order": {"items": ["Torta di Nocciole"]},
    })
    assert r["allergen_status"] == "conflict"
    assert "nuts" in r["matched_allergens"]
    assert r["conflicts"][0]["item"] == "Torta di Nocciole"


def test_screen_allergens_clear_when_no_intersection():
    r = H.screen_allergens({
        "ticket_id": "T",
        "dietary_flags": ["nuts"],
        "order": {"items": ["Branzino al Forno"]},
    })
    assert r["allergen_status"] == "clear"


# --------------------------------------------------------------------------- #
# Side-effect acknowledgement + idempotent, deterministic action_id
# --------------------------------------------------------------------------- #

def test_fire_ticket_acknowledgement_and_determinism():
    a = H.fire_ticket({"ticket_id": "TKT-9", "order": {"items": []}})
    b = H.fire_ticket({"ticket_id": "TKT-9", "order": {"items": []}})
    assert a["acknowledged"] is True and a["status"] == "performed"
    assert a["action_id"] == b["action_id"]  # same ticket -> same action_id (idempotent anchor)
    assert a["ticket_ref"].startswith("KDS-")


def test_charge_payment_captured():
    r = H.charge_payment({"ticket_id": "TKT-1", "amount": 42.0, "tender": "card"})
    assert r["payment_status"] == "captured"
    assert r["acknowledged"] is True and r["status"] == "performed"
    assert r["payment_ref"].startswith("PAY-")


def test_charge_payment_declined_by_first_pass_tender_hint():
    # First pass: decline is driven by the trigger's tender_hint (no retry artifact yet).
    r = H.charge_payment({"ticket_id": "TKT-1", "amount": 42.0, "tender_hint": "declined"})
    assert r["payment_status"] == "declined"
    assert r["acknowledged"] is False and r["status"] == "rejected"
    assert r["payment_ref"] == ""


def test_charge_payment_retry_tender_overrides_hint_and_terminates_loop():
    # The human's retry tender (top precedence) overrides a "declined" first-pass hint -> loop terminates.
    r = H.charge_payment({"ticket_id": "TKT-1", "amount": 42.0, "tender": "card", "tender_hint": "declined"})
    assert r["payment_status"] == "captured"
    assert r["acknowledged"] is True and r["status"] == "performed"


# --------------------------------------------------------------------------- #
# get_menu / generate_bill
# --------------------------------------------------------------------------- #

def test_get_menu_shape():
    m = H.get_menu({"ticket_id": "T"})
    assert m["currency"] == "USD"
    assert [s["name"] for s in m["sections"]] == ["Antipasti", "Primi", "Secondi", "Dolci"]
    assert any(i["available"] is False for s in m["sections"] for i in s["items"])  # Osso Buco (86)


def test_generate_bill_prices_items_from_menu():
    # Prices are resolved from the menu, not the order: Spaghetti (18.0) + Sorbetto (8.0) = 26.0.
    b = H.generate_bill({"ticket_id": "T", "order": {"items": [
        "Spaghetti alla Carbonara",
        "Sorbetto al Limone",
    ]}})
    assert b["subtotal"] == 26.0
    assert [li["price"] for li in b["line_items"]] == [18.0, 8.0]
    assert b["total"] == pytest.approx(26.0 + round(26.0 * 0.0875, 2))
