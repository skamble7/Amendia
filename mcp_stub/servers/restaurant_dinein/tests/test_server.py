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
    sample_order = {"lines": [{"name": "Margherita Pizza", "qty": 2, "price": 16.0, "tags": ["gluten"]}]}
    args = {
        "ticket_id": "TKT-1",
        "order": sample_order,
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
    ok = H.validate_order({"ticket_id": "T", "order": {"lines": [{"name": "Garden Salad"}]}})
    assert ok["order_verdict"] == "ok"


def test_validate_order_needs_info_on_86_item():
    r = H.validate_order({"ticket_id": "T", "order": {"lines": [{"name": "Lobster Thermidor (86)"}]}})
    assert r["order_verdict"] == "needs_info"
    assert r["unavailable_items"]


def test_validate_order_needs_info_on_unavailable_flag():
    r = H.validate_order({"ticket_id": "T", "order": {"lines": [{"name": "Special", "available": False}]}})
    assert r["order_verdict"] == "needs_info"


def test_screen_allergens_conflict_on_flag_intersection():
    r = H.screen_allergens({
        "ticket_id": "T",
        "party": {"dietary_flags": ["nuts"]},
        "order": {"lines": [{"name": "Peanut Parfait", "tags": ["nuts", "dairy"]}]},
    })
    assert r["allergen_status"] == "conflict"
    assert "nuts" in r["matched_allergens"]


def test_screen_allergens_clear_when_no_intersection():
    r = H.screen_allergens({
        "ticket_id": "T",
        "party": {"dietary_flags": ["nuts"]},
        "order": {"lines": [{"name": "Grilled Salmon", "tags": ["fish"]}]},
    })
    assert r["allergen_status"] == "clear"


# --------------------------------------------------------------------------- #
# Side-effect acknowledgement + idempotent, deterministic action_id
# --------------------------------------------------------------------------- #

def test_fire_ticket_acknowledgement_and_determinism():
    a = H.fire_ticket({"ticket_id": "TKT-9", "order": {"lines": []}})
    b = H.fire_ticket({"ticket_id": "TKT-9", "order": {"lines": []}})
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
    assert any(i["available"] is False for s in m["sections"] for i in s["items"])  # an 86'd item exists


def test_generate_bill_totals():
    b = H.generate_bill({"ticket_id": "T", "order": {"lines": [
        {"name": "Margherita Pizza", "qty": 2, "price": 16.0},
        {"name": "Sorbet", "qty": 1, "price": 8.0},
    ]}})
    assert b["subtotal"] == 40.0
    assert b["total"] == pytest.approx(40.0 + round(40.0 * 0.0875, 2))
