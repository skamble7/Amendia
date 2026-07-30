# tests/_restaurant_copilot.py
"""Golden restaurant fixture for the onboarding copilot: the 6 dine-in MCP tools (verbatim schemas), a fake
introspector, a recorded CopilotProposal, and a fake LLM client. No live network, no ConfigForge, no model.

Domain-neutral platform code, restaurant only as a fixture — this file lives entirely in the test layer.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from app.services.mcp_introspect import RawMcpTool

BPMN_PATH = Path(__file__).resolve().parent / "fixtures" / "restaurant_dine_in.bpmn"


def restaurant_bpmn() -> str:
    return BPMN_PATH.read_text()


# The USER-PROVIDED trigger (a sample party-seated event; the copilot derives the schema) + manual triage rules.
def restaurant_trigger() -> Dict[str, Any]:
    return {"ticket_id": "T-1", "order_type": "dine_in", "table": "5", "party_size": 2,
            "dietary_flags": ["nuts"], "seated_at": "2026-01-01T00:00:00Z"}


def restaurant_triage() -> List[Dict[str, Any]]:
    return [{"rule_id": "dine_in", "priority": 100,
             "when": {"field": "order_type", "op": "eq", "value": "dine_in"}}]


# --------------------------------------------------------------------------- #
# The 6 dine-in MCP tools (schemas verbatim from the restaurant_dinein MCP server)
# --------------------------------------------------------------------------- #
_ORDER_INPUT = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "string"}}}}
_ACK = {"acknowledged": {"type": "boolean"}, "action_id": {"type": "string"},
        "status": {"type": "string", "enum": ["performed", "queued", "rejected"]}}


def restaurant_tools() -> List[RawMcpTool]:
    return [
        RawMcpTool(
            name="get_menu", description="Return the house menu (sections, items, prices, availability, tags).",
            input_schema={"type": "object", "additionalProperties": False,
                          "properties": {"request": {"type": "object"}, "ticket_id": {"type": "string"},
                                         "section_filter": {"type": "string"}}},
            output_schema={"type": "object", "additionalProperties": False,
                           "properties": {"sections": {"type": "array", "items": {"type": "object"}},
                                          "currency": {"type": "string"}},
                           "required": ["sections", "currency"]}),
        RawMcpTool(
            name="validate_order", description="Validate a dine-in order; returns an order verdict.",
            input_schema={"type": "object", "additionalProperties": False,
                          "properties": {"order": _ORDER_INPUT, "ticket_id": {"type": "string"},
                                         "hint": {"type": "string"}}},
            output_schema={"type": "object", "additionalProperties": False,
                           "properties": {"order_verdict": {"type": "string", "enum": ["ok", "needs_info"]},
                                          "issues": {"type": "array", "items": {"type": "string"}},
                                          "unavailable_items": {"type": "array", "items": {"type": "string"}}},
                           "required": ["order_verdict"]}),
        RawMcpTool(
            name="screen_allergens", description="Screen an order against the party's dietary flags.",
            input_schema={"type": "object", "additionalProperties": False,
                          "properties": {"order": _ORDER_INPUT, "party": {"type": "object"},
                                         "dietary_flags": {"type": "array", "items": {"type": "string"}},
                                         "ticket_id": {"type": "string"}, "hint": {"type": "string"}}},
            output_schema={"type": "object", "additionalProperties": False,
                           "properties": {"allergen_status": {"type": "string", "enum": ["clear", "conflict"]},
                                          "conflicts": {"type": "array", "items": {"type": "object"}},
                                          "matched_allergens": {"type": "array", "items": {"type": "string"}}},
                           "required": ["allergen_status"]}),
        RawMcpTool(
            name="generate_bill", description="Price the order into an itemized bill.",
            input_schema={"type": "object", "additionalProperties": False,
                          "properties": {"order": _ORDER_INPUT, "ticket_id": {"type": "string"}}},
            output_schema={"type": "object", "additionalProperties": False,
                           "properties": {"line_items": {"type": "array", "items": {"type": "object"}},
                                          "subtotal": {"type": "number"}, "tax": {"type": "number"},
                                          "total": {"type": "number"}, "currency": {"type": "string"}},
                           "required": ["total", "currency"]}),
        RawMcpTool(
            name="fire_ticket", description="Fire the approved ticket to the kitchen (side-effectful).",
            input_schema={"type": "object", "additionalProperties": False,
                          "properties": {"order": _ORDER_INPUT, "ticket_id": {"type": "string"}}},
            output_schema={"type": "object", "additionalProperties": False,
                           "properties": {**_ACK, "ticket_ref": {"type": "string"}, "fired_at": {"type": "string"}},
                           "required": ["acknowledged", "action_id", "status"]}),
        RawMcpTool(
            name="charge_payment", description="Charge the bill at the POS and issue the receipt (side-effectful).",
            input_schema={"type": "object", "additionalProperties": False,
                          "properties": {"bill": {"type": "object"}, "ticket_id": {"type": "string"},
                                         "tender": {"type": "string"}, "tender_hint": {"type": "string"},
                                         "amount": {"type": "number"}}},
            output_schema={"type": "object", "additionalProperties": False,
                           "properties": {**_ACK, "payment_status": {"type": "string", "enum": ["captured", "declined"]},
                                          "payment_ref": {"type": "string"}, "amount": {"type": "number"},
                                          "charged_at": {"type": "string"}},
                           "required": ["acknowledged", "action_id", "status", "payment_status"]}),
    ]


# --------------------------------------------------------------------------- #
# Fake LLM client — serves a queue of recorded JSON responses (repeats the last).
# --------------------------------------------------------------------------- #
class FakeLLMClient:
    def __init__(self, responses: List[str]) -> None:
        self._responses = list(responses)
        self.calls: List[List[Dict[str, str]]] = []

    async def chat(self, messages, *, profile=None):
        self.calls.append(messages)
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return SimpleNamespace(text=self._responses[idx], raw={"provider": "fake", "model": "fake-copilot-1"})


class FakeConfigForgeLoader:
    """Stands in for ``polyllm.RemoteConfigLoader`` — resolves a ref to a fake ``LLMClient`` with NO network and
    NO ConfigForge. ``PROFILES`` maps ref → the proposal JSON that ref's model returns (a distinct profile per
    ref); an unknown ref raises (like ConfigForge's 404). ``LOADED`` records every ref resolved, so a test can
    prove exactly which ref the copilot picked (default vs per-request override) — the config-driven contract."""

    PROFILES: Dict[str, str] = {}
    LOADED: List[str] = []

    def __init__(self, base_url=None, **kw):
        self.base_url = base_url

    async def load(self, ref):
        FakeConfigForgeLoader.LOADED.append(ref)
        if ref not in FakeConfigForgeLoader.PROFILES:
            raise RuntimeError(f"ConfigForge 404: no config for ref '{ref}'")
        return FakeLLMClient([FakeConfigForgeLoader.PROFILES[ref]])

    @classmethod
    def reset(cls, profiles: Dict[str, str]):
        cls.PROFILES = dict(profiles)
        cls.LOADED = []


# --------------------------------------------------------------------------- #
# The recorded CopilotProposal for the restaurant (what a strong model would return).
# ``fire_hitl`` lets a test inject a TOO-WEAK gate for the side-effect-floor clamp assertion.
# --------------------------------------------------------------------------- #
def restaurant_proposal(*, fire_hitl: str = "none", process_hitl: str = "approve_actions") -> Dict[str, Any]:
    def order_consumer(el: str, tool: str, output_name: str | None = None, extra_map=None, hitl="none", role=None):
        e: Dict[str, Any] = {"element_id": el, "executor": {"type": "capability", "capability_tool": tool},
                             "hitl": {"mode": hitl, **({"role": role} if role else {})},
                             "input_map": [{"field": "order", "from": "artifact", "name": "order"}] + (extra_map or []),
                             "confidence": 0.9, "rationale": f"{el} calls {tool}"}
        if output_name:
            e["output_name"] = output_name
        return e

    def human(el, role, outputs=None, ro=None, conf=0.85):
        return {"element_id": el, "executor": {"type": "human", "role": role},
                "hitl": {"mode": "manual", "role": role},
                "outputs": [{"name": n, "human_authored": True} for n in (outputs or [])],
                "read_only_inputs": [{"name": n, "source_output": s} for (n, s) in (ro or [])],
                "confidence": conf, "rationale": f"{el} is human work"}

    return {
        "summary": "A seated party is shown the menu, the diner selects items and the server confirms the order; "
                   "the kitchen validates availability and screens allergens (revising on a problem), fires the "
                   "ticket, prepares and serves it; a bill is generated, the diner presents payment and the manager "
                   "charges it (resolving on a decline).",
        "elements": [
            {"element_id": "Task_PresentMenu", "executor": {"type": "capability", "capability_tool": "get_menu"},
             "hitl": {"mode": "none"}, "confidence": 0.9, "rationale": "shows the menu"},
            human("Task_SelectItems", "role.rest_stan.diner", outputs=["order"], ro=[("menu", "get_menu_output")]),
            human("Task_TakeOrder", "role.rest_stan.server", ro=[("order", "order")]),
            order_consumer("Task_ValidateOrder", "validate_order", output_name="validation"),
            human("Task_ReviseOrder", "role.rest_stan.diner", outputs=["order"]),
            order_consumer("Task_ScreenAllergens", "screen_allergens", output_name="allergen",
                           extra_map=[{"field": "dietary_flags", "from": "trigger", "path": "dietary_flags"}]),
            order_consumer("Task_FireTicket", "fire_ticket", hitl=fire_hitl, role="role.rest_stan.kitchen"),
            human("Task_PrepareReady", "role.rest_stan.kitchen"),
            human("Task_ServiceRecovery", "role.rest_stan.manager", conf=0.4),   # low-confidence → a stable open question
            human("Task_ServeOrder", "role.rest_stan.server"),
            order_consumer("Task_GenerateBill", "generate_bill"),
            human("Task_PresentPayment", "role.rest_stan.diner", outputs=["payment"]),
            {"element_id": "Task_ProcessPayment", "executor": {"type": "capability", "capability_tool": "charge_payment"},
             "hitl": {"mode": process_hitl, "role": "role.rest_stan.manager"}, "output_name": "receipt",
             "input_map": [{"field": "tender", "from": "artifact", "name": "payment", "path": "tender"}],
             "confidence": 0.88, "rationale": "charges the bill"},
            human("Task_ResolvePayment", "role.rest_stan.server", outputs=["payment"]),
        ],
        "trigger_schema": {"type": "object", "additionalProperties": False,
                           "properties": {"ticket_id": {"type": "string"},
                                          "order_type": {"type": "string", "enum": ["dine_in"]},
                                          "dietary_flags": {"type": "array", "items": {"type": "string"}}},
                           "required": ["ticket_id", "order_type"]},
        "trigger_confidence": 0.6,
        "triage_rules": [{"rule_id": "dine_in", "priority": 100,
                          "when": {"field": "order_type", "op": "eq", "value": "dine_in"},
                          "confidence": 0.4, "rationale": "route dine-in tickets to this pack"}],
    }


def restaurant_proposal_json(**kw) -> str:
    return json.dumps(restaurant_proposal(**kw))
