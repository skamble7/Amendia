# schemas.py
"""Per-tool JSON Schemas (draft 2020-12) for the restaurant dine-in MCP server.

These are the contract. The process-registry onboarding wizard
(``POST /capabilities/introspect-mcp``, ADR-025) turns each tool's ``inputSchema`` and
``outputSchema`` into two artifact schemas + one ``kind: mcp`` capability, and the
``restaurant-dinein`` pack's exclusive gateways branch on ``validation.order_verdict`` and
``allergen.allergen_status`` — so the **output** shapes here must match the spec exactly.

This is the domain-simple twin of ``wire_transfer_exception`` (the same design rules, a friendlier
domain): the platform image gains **zero** restaurant code; the process runs as onboarded data + this
external MCP server, exactly like the re-homed wire pack (ADR-047 D2).

Design rules (mirroring what the wizard enforces in
``process-registry/app/services/mcp_introspect.py``):
- root ``type: object`` on every schema;
- no external ``$ref`` (schemas are fully self-contained);
- **outputs are closed** (``additionalProperties: false`` recursively) — they're the
  contract the artifacts + gateways depend on;
- **inputs are closed at the root** but carry *open* payload objects so a caller can pass a whole
  ``order`` / ``bill`` / ``party`` without being rejected.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

DRAFT = "https://json-schema.org/draft/2020-12/schema"


# --------------------------------------------------------------------------- #
# Small builders
# --------------------------------------------------------------------------- #

def _closed(properties: Dict[str, Any], *, required: Iterable[str] = ()) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": properties}
    if required:
        schema["required"] = list(required)
    return schema


def _open() -> Dict[str, Any]:
    """A permissive nested object — a caller may pass any structure inside it."""
    return {"type": "object"}


def _arr(items: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "array", "items": items}


_STR = {"type": "string"}
_NUM = {"type": "number"}
_BOOL = {"type": "boolean"}
_STR_ARR = {"type": "array", "items": {"type": "string"}}


def _input(properties: Dict[str, Any]) -> Dict[str, Any]:
    """A CLOSED input: root object, ``additionalProperties: false``, no required fields — the dumb handlers
    tolerate whatever declared props they get and read only what they need. The server's ``check_compliance``
    ENFORCES the closed root (MCP Implementor Guideline), so every field a binding's ``input_map`` composite
    sends for this tool MUST be declared here — else the server 400-rejects the call."""
    return {"$schema": DRAFT, "type": "object", "additionalProperties": False, "properties": properties}


def _output(properties: Dict[str, Any], required: Iterable[str]) -> Dict[str, Any]:
    return {"$schema": DRAFT, "type": "object", "additionalProperties": False,
            "properties": properties, "required": list(required)}


def _ack_output(extra: Dict[str, Any] | None = None, *, extra_required: Iterable[str] = ()) -> Dict[str, Any]:
    """The guideline acknowledgement shape shared by the two side-effectful action tools."""
    props: Dict[str, Any] = {
        "acknowledged": _BOOL,
        "action_id": _STR,
        "status": {"type": "string", "enum": ["performed", "queued", "rejected"]},
    }
    if extra:
        props.update(extra)
    return _output(props, required=["acknowledged", "action_id", "status", *extra_required])


# --------------------------------------------------------------------------- #
# Enums referenced by the pack / gateways
# --------------------------------------------------------------------------- #

ORDER_VERDICTS = ["ok", "needs_info"]
ALLERGEN_STATUSES = ["clear", "conflict"]
PAYMENT_STATUSES = ["captured", "declined"]


# --------------------------------------------------------------------------- #
# 1) get_menu (read_only)
# --------------------------------------------------------------------------- #

GET_MENU_INPUT = _input({
    "request": _open(),
    "ticket_id": _STR,
    "section_filter": _STR,
})

GET_MENU_OUTPUT = _output(
    {
        "sections": _arr(_closed({
            "name": _STR,
            "items": _arr(_closed({
                "name": _STR,
                "price": _NUM,
                "available": _BOOL,
                "tags": _STR_ARR,
            })),
        })),
        "currency": _STR,
    },
    required=["sections", "currency"],
)


# --------------------------------------------------------------------------- #
# 2) validate_order (read_only) — emits the gateway field validation.order_verdict
# --------------------------------------------------------------------------- #

VALIDATE_ORDER_INPUT = _input({
    "order": _open(),
    "ticket_id": _STR,
    # A demo steering hint: "ok" forces a clean order; "needs_info"/"unavailable" forces a revise loop.
    "hint": _STR,
})

VALIDATE_ORDER_OUTPUT = _output(
    {
        "order_verdict": {"type": "string", "enum": ORDER_VERDICTS},
        "issues": _STR_ARR,
        "unavailable_items": _STR_ARR,
    },
    required=["order_verdict"],  # gateway reads validation.order_verdict — MUST be required
)


# --------------------------------------------------------------------------- #
# 3) screen_allergens (read_only) — emits the gateway field allergen.allergen_status
# --------------------------------------------------------------------------- #

SCREEN_ALLERGENS_INPUT = _input({
    "order": _open(),
    "party": _open(),
    "ticket_id": _STR,
    "hint": _STR,
})

SCREEN_ALLERGENS_OUTPUT = _output(
    {
        "allergen_status": {"type": "string", "enum": ALLERGEN_STATUSES},
        "conflicts": _arr(_closed({"item": _STR, "allergen": _STR})),
        "matched_allergens": _STR_ARR,
    },
    required=["allergen_status"],  # gateway reads allergen.allergen_status — MUST be required
)


# --------------------------------------------------------------------------- #
# 4) generate_bill (read_only)
# --------------------------------------------------------------------------- #

GENERATE_BILL_INPUT = _input({"order": _open(), "ticket_id": _STR})

GENERATE_BILL_OUTPUT = _output(
    {
        "line_items": _arr(_closed({"name": _STR, "qty": _NUM, "price": _NUM})),
        "subtotal": _NUM,
        "tax": _NUM,
        "total": _NUM,
        "currency": _STR,
    },
    required=["total", "currency"],
)


# --------------------------------------------------------------------------- #
# 5) fire_ticket (side-effectful)
# --------------------------------------------------------------------------- #

FIRE_TICKET_INPUT = _input({"order": _open(), "ticket_id": _STR})

FIRE_TICKET_OUTPUT = _ack_output({"ticket_ref": _STR, "fired_at": _STR})


# --------------------------------------------------------------------------- #
# 6) charge_payment (side-effectful) — emits the gateway field receipt.payment_status
# --------------------------------------------------------------------------- #

CHARGE_PAYMENT_INPUT = _input({
    "bill": _open(),
    "ticket_id": _STR,
    # Effective tender = ``tender`` (the human's retry choice from art.dining.payment_retry, top precedence)
    # else ``tender_hint`` (the trigger's first-pass tender). A "declined" effective tender drives the
    # payment-resolution loop; because the human's retry supplies a NON-declined tender, the loop always
    # terminates — the same human-authored-precedence pattern that fixes the wire needs-info loop.
    "tender": _STR,
    "tender_hint": _STR,
    "amount": _NUM,
})

CHARGE_PAYMENT_OUTPUT = _ack_output(
    {
        "payment_status": {"type": "string", "enum": PAYMENT_STATUSES},
        "payment_ref": _STR,
        "amount": _NUM,
        "charged_at": _STR,
    },
    extra_required=["payment_status"],  # gateway reads receipt.payment_status — MUST be required
)
