# handlers.py
"""Dumb, deterministic tool handlers + the tool registry + the compliance self-check.

Every handler is a pure function of its arguments — no clock, no randomness, no network — so the
same input always yields the same output (including ``action_id``). Handlers echo salient input
fields into their outputs so a human reviewing a HITL task sees plausible, connected data, and they
expose small **steering hints** so a demo can deterministically drive every gateway/loop branch.

This module does **not** import the ``mcp`` SDK, so the schemas, handlers, and compliance self-check
are testable without it (``server.py`` is the only place the SDK is used).
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Dict, List

from . import external as ext
from . import schemas as S

# A fixed, deterministic timestamp used when the input carries none — keeps outputs stable.
_FIXED_TS = "2025-01-01T00:00:00Z"

ACTION_TOOLS = {"fire_ticket", "charge_payment"}


# --------------------------------------------------------------------------- #
# Input digging (permissive — accept fields at the top level or inside a payload object)
# --------------------------------------------------------------------------- #

def _payload(args: Dict[str, Any], *names: str) -> Dict[str, Any]:
    for n in names:
        v = args.get(n)
        if isinstance(v, dict):
            return v
    return {}


def _dig(args: Dict[str, Any], key: str, default: Any = None) -> Any:
    """Find ``key`` at the top level or one level down inside any payload object."""
    if key in args and args[key] is not None:
        return args[key]
    for v in args.values():
        if isinstance(v, dict) and v.get(key) is not None:
            return v[key]
    return default


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _lower(v: Any) -> str:
    return str(v).lower() if v is not None else ""


def ticket_id(args: Dict[str, Any]) -> str:
    return str(_dig(args, "ticket_id", "unknown-ticket"))


def action_id(tool: str, tkt: str) -> str:
    """Deterministic, idempotent, auditable — a hash of the ticket id + tool name."""
    return "act-" + hashlib.sha256(f"{tool}:{tkt}".encode("utf-8")).hexdigest()[:16]


def _ts(args: Dict[str, Any]) -> str:
    return str(_dig(args, "occurred_at", None) or _dig(args, "as_of", None) or _FIXED_TS)


def _order_lines(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    order = _payload(args, "order")
    lines = order.get("lines") if isinstance(order.get("lines"), list) else []
    return [ln for ln in lines if isinstance(ln, dict)]


def _dietary_flags(args: Dict[str, Any]) -> List[str]:
    flags = _dig(args, "dietary_flags", None)
    if flags is None:
        party = _payload(args, "party", "order")
        flags = party.get("dietary_flags")
    return [_lower(f) for f in flags] if isinstance(flags, list) else []


# --------------------------------------------------------------------------- #
# Read-only handlers
# --------------------------------------------------------------------------- #

def get_menu(args: Dict[str, Any]) -> Dict[str, Any]:
    """A small deterministic house menu. ``available: false`` items and ``tags`` (allergens) let a
    demo compose an order that trips validate_order / screen_allergens."""
    menu = {
        "currency": "USD",
        "sections": [
            {"name": "Starters", "items": [
                {"name": "Garden Salad", "price": 9.0, "available": True, "tags": []},
                {"name": "Pesto Bruschetta", "price": 11.0, "available": True, "tags": ["nuts", "gluten"]},
            ]},
            {"name": "Mains", "items": [
                {"name": "Margherita Pizza", "price": 16.0, "available": True, "tags": ["gluten", "dairy"]},
                {"name": "Grilled Salmon", "price": 26.0, "available": True, "tags": ["fish"]},
                {"name": "Lobster Thermidor (86)", "price": 48.0, "available": False, "tags": ["shellfish", "dairy"]},
            ]},
            {"name": "Desserts", "items": [
                {"name": "Sorbet", "price": 8.0, "available": True, "tags": []},
                {"name": "Peanut Parfait", "price": 10.0, "available": True, "tags": ["nuts", "dairy"]},
            ]},
        ],
    }
    section_filter = _lower(_dig(args, "section_filter"))
    if section_filter:
        menu["sections"] = [s for s in menu["sections"] if _lower(s["name"]) == section_filter] or menu["sections"]
    return menu


def validate_order(args: Dict[str, Any]) -> Dict[str, Any]:
    """Verdict ``ok`` | ``needs_info``. ``needs_info`` (the revise loop) when a requested item is 86'd
    (name contains "86" or ``available: false``), or when the hint forces it."""
    hint = _lower(_dig(args, "hint"))
    lines = _order_lines(args)
    unavailable: List[str] = []
    for ln in lines:
        name = str(ln.get("name") or ln.get("item_id") or "")
        if "86" in name or ln.get("available") is False:
            unavailable.append(name)
    if hint == "ok":
        verdict, unavailable = "ok", []
    elif hint in ("needs_info", "unavailable", "revise") or unavailable:
        verdict = "needs_info"
    else:
        verdict = "ok"
    issues = ([f"'{n}' is currently 86'd (unavailable)" for n in unavailable]
              or (["order needs clarification"] if verdict == "needs_info" else []))
    return {"order_verdict": verdict, "issues": issues, "unavailable_items": unavailable}


def screen_allergens(args: Dict[str, Any]) -> Dict[str, Any]:
    """Status ``clear`` | ``conflict``. ``conflict`` when an ordered item's ``tags`` intersect the
    party's ``dietary_flags`` (e.g. a "nuts"-flagged guest orders the Peanut Parfait), or the hint forces it."""
    hint = _lower(_dig(args, "hint"))
    flags = set(_dietary_flags(args))
    lines = _order_lines(args)
    conflicts: List[Dict[str, str]] = []
    matched: List[str] = []
    for ln in lines:
        tags = ln.get("tags") if isinstance(ln.get("tags"), list) else []
        for t in tags:
            if _lower(t) in flags:
                conflicts.append({"item": str(ln.get("name") or "item"), "allergen": _lower(t)})
                matched.append(_lower(t))
    if hint == "clear":
        status, conflicts, matched = "clear", [], []
    elif hint == "conflict" or conflicts:
        status = "conflict"
    else:
        status = "clear"
    return {"allergen_status": status, "conflicts": conflicts, "matched_allergens": sorted(set(matched))}


def generate_bill(args: Dict[str, Any]) -> Dict[str, Any]:
    lines = _order_lines(args)
    line_items: List[Dict[str, Any]] = []
    subtotal = 0.0
    for ln in lines:
        qty = _num(ln.get("qty"), 1.0)
        price = _num(ln.get("price"), 12.0)
        subtotal += qty * price
        line_items.append({"name": str(ln.get("name") or "item"), "qty": qty, "price": price})
    if not line_items:  # a bill always has at least one line for the demo
        line_items = [{"name": "House selection", "qty": 1.0, "price": 24.0}]
        subtotal = 24.0
    tax = round(subtotal * 0.0875, 2)
    total = round(subtotal + tax, 2)
    return {"line_items": line_items, "subtotal": round(subtotal, 2), "tax": tax, "total": total, "currency": "USD"}


# --------------------------------------------------------------------------- #
# Side-effectful action handlers (return the guideline acknowledgement)
# --------------------------------------------------------------------------- #

def fire_ticket(args: Dict[str, Any]) -> Dict[str, Any]:
    tkt = ticket_id(args)
    return {
        "acknowledged": True,
        "action_id": action_id("fire_ticket", tkt),
        "status": "performed",
        "ticket_ref": ext.post_kitchen_ticket(tkt),
        "fired_at": _ts(args),
    }


def charge_payment(args: Dict[str, Any]) -> Dict[str, Any]:
    """Captures the bill at the POS. Declines (driving the payment-resolution loop) when the *effective*
    tender is "declined" — a declined charge moves **no** money (``acknowledged: false``,
    ``status: "rejected"``).

    Effective tender = ``tender`` (the human's retry choice, top precedence) else ``tender_hint`` (the
    trigger's first-pass tender). Because a human retry supplies a non-declined tender, the resolve loop
    always terminates — the human-authored-precedence pattern that fixes the wire needs-info loop.
    """
    tkt = ticket_id(args)
    retry_tender = _lower(_dig(args, "tender"))
    hint_tender = _lower(_dig(args, "tender_hint"))
    effective = retry_tender or hint_tender
    amount = _num(_dig(args, "amount"), 0.0)
    declined = effective in ("declined", "decline", "fail")
    if declined:
        return {
            "acknowledged": False,
            "action_id": action_id("charge_payment", tkt),
            "status": "rejected",
            "payment_status": "declined",
            "payment_ref": "",
            "amount": amount,
            "charged_at": _ts(args),
        }
    return {
        "acknowledged": True,
        "action_id": action_id("charge_payment", tkt),
        "status": "performed",
        "payment_status": "captured",
        "payment_ref": ext.post_payment(tkt),
        "amount": amount,
        "charged_at": _ts(args),
    }


# --------------------------------------------------------------------------- #
# The tool registry — the 6 capability tools the wizard onboards.
# --------------------------------------------------------------------------- #

class ToolSpec(dict):
    """A plain dict with attribute access, for readability at call sites."""

    def __getattr__(self, k: str) -> Any:  # pragma: no cover - convenience
        return self[k]


def _spec(name, description, side_effect, input_schema, output_schema, handler) -> ToolSpec:
    return ToolSpec(name=name, description=description, side_effect=side_effect,
                    input_schema=input_schema, output_schema=output_schema, handler=handler)


TOOLS: List[ToolSpec] = [
    _spec("get_menu", "Return the house menu (sections, items, prices, availability, allergen tags).",
          "read_only", S.GET_MENU_INPUT, S.GET_MENU_OUTPUT, get_menu),
    _spec("validate_order", "Validate a dine-in order for availability/completeness; returns an order verdict.",
          "read_only", S.VALIDATE_ORDER_INPUT, S.VALIDATE_ORDER_OUTPUT, validate_order),
    _spec("screen_allergens", "Screen an order against the party's dietary flags; returns an allergen status.",
          "read_only", S.SCREEN_ALLERGENS_INPUT, S.SCREEN_ALLERGENS_OUTPUT, screen_allergens),
    _spec("generate_bill", "Price the order into an itemized bill (subtotal, tax, total).",
          "read_only", S.GENERATE_BILL_INPUT, S.GENERATE_BILL_OUTPUT, generate_bill),
    _spec("fire_ticket", "Fire the approved ticket to the kitchen display system (side-effectful).",
          "side_effectful", S.FIRE_TICKET_INPUT, S.FIRE_TICKET_OUTPUT, fire_ticket),
    _spec("charge_payment", "Charge the bill at the POS and issue the receipt (side-effectful).",
          "side_effectful", S.CHARGE_PAYMENT_INPUT, S.CHARGE_PAYMENT_OUTPUT, charge_payment),
]

TOOLS_BY_NAME: Dict[str, ToolSpec] = {t["name"]: t for t in TOOLS}


# --------------------------------------------------------------------------- #
# Compliance self-check — the exact properties the onboarding wizard enforces
# (process-registry/app/services/mcp_introspect.py), asserted at import time so the
# server refuses to start non-compliant.
# --------------------------------------------------------------------------- #

def _iter_objects(schema: Any):
    """Yield every sub-schema that describes an object (has type 'object' or 'properties')."""
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            yield schema
        for v in schema.values():
            yield from _iter_objects(v)
    elif isinstance(schema, list):
        for item in schema:
            yield from _iter_objects(item)


def _has_ref(schema: Any) -> bool:
    if isinstance(schema, dict):
        if "$ref" in schema:
            return True
        return any(_has_ref(v) for v in schema.values())
    if isinstance(schema, list):
        return any(_has_ref(i) for i in schema)
    return False


def check_compliance(tools: List[ToolSpec] = TOOLS) -> None:
    """Assert every capability tool is Amendia-MCP-compliant. Raises ``AssertionError``
    (with the offending tool + reason) on the first violation."""
    assert len(tools) == 6, f"expected 6 tools (4 read-only + 2 side-effectful), found {len(tools)}"
    for t in tools:
        n = t["name"]
        insch, outsch = t["input_schema"], t["output_schema"]
        assert isinstance(insch, dict) and insch.get("type") == "object", f"{n}: inputSchema root must be object"
        assert isinstance(outsch, dict) and outsch.get("type") == "object", f"{n}: outputSchema root must be object"
        assert not _has_ref(insch), f"{n}: inputSchema must not use $ref"
        assert not _has_ref(outsch), f"{n}: outputSchema must not use $ref"
        assert insch.get("additionalProperties") is False, f"{n}: inputSchema root must set additionalProperties:false"
        for obj in _iter_objects(outsch):
            assert obj.get("additionalProperties") is False, f"{n}: every output object must set additionalProperties:false"
        if t["side_effect"] == "side_effectful":
            req = set(outsch.get("required", []))
            assert {"acknowledged", "action_id", "status"} <= req, \
                f"{n}: action tool output must require acknowledged + action_id + status"


# Fail fast at import if anything drifts out of compliance.
check_compliance()
