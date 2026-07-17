"""Schema / compliance / determinism tests for the wire-transfer-exception MCP server.

Most tests exercise the registry (``schemas.py`` + ``handlers.py``) directly and need only
``jsonschema`` — no ``mcp`` SDK. One SDK-gated test drives ``tools/list`` + ``tools/call`` over
the SDK's in-memory transport to prove the wire shape (structured content) end to end.
"""
from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from wire_transfer_exception_mcp import schemas as S
from wire_transfer_exception_mcp.handlers import TOOLS, TOOLS_BY_NAME, check_compliance

EXPECTED_TOOLS = {
    "enrich_investigation", "assess_beneficiary", "draft_rfi", "draft_repair", "screen_party",
    "apply_repair", "notify_parties", "record_resolution", "draft_return", "execute_return",
}
ACTION_TOOLS = {"apply_repair", "notify_parties", "execute_return"}

# One representative input per tool (permissive; the handlers tolerate more/less).
REP = {
    "enrich_investigation": {"exception_id": "exc-1", "envelope": {"payment": {
        "msg_type": "pacs.008", "amount": 125000, "currency": "USD",
        "creditor": {"name": "ACME BENEFICIARY LTD"}, "debtor": {"name": "ORIGINATOR CORP"}}}},
    "assess_beneficiary": {"exception_id": "exc-1", "reason_codes": ["AC01"]},
    "draft_rfi": {"exception_id": "exc-1", "missing_fields": ["beneficiary_account"]},
    "draft_repair": {"exception_id": "exc-1", "dossier": {"field": "creditor_account"}},
    "screen_party": {"exception_id": "exc-1", "party": {"name": "ACME BENEFICIARY LTD"}},
    "apply_repair": {"exception_id": "exc-1", "repair": {"field": "creditor_account"}},
    "notify_parties": {"exception_id": "exc-1", "recipients": ["originator", "beneficiary_bank"]},
    "record_resolution": {"exception_id": "exc-1"},
    "draft_return": {"exception_id": "exc-1", "dossier": {"payment": {"amount": 125000, "currency": "USD"}}},
    "execute_return": {"exception_id": "exc-1", "return_instruction": {"return_reason_code": "AC04"}},
}


def test_exactly_ten_capability_tools():
    assert len(TOOLS) == 10
    assert {t["name"] for t in TOOLS} == EXPECTED_TOOLS


def test_compliance_self_check_passes():
    check_compliance()  # raises AssertionError on any violation
    for t in TOOLS:
        assert t["input_schema"]["type"] == "object"
        assert t["output_schema"]["type"] == "object"
        assert t["input_schema"].get("additionalProperties") is False


def test_action_tools_output_requires_ack_fields():
    for name in ACTION_TOOLS:
        required = set(TOOLS_BY_NAME[name]["output_schema"]["required"])
        assert {"acknowledged", "action_id", "status"} <= required


def test_all_schemas_are_valid_draft_2020_12():
    for t in TOOLS:
        Draft202012Validator.check_schema(t["input_schema"])
        Draft202012Validator.check_schema(t["output_schema"])


def test_each_tool_output_validates_against_its_output_schema():
    for t in TOOLS:
        out = t["handler"](REP[t["name"]])
        Draft202012Validator(t["output_schema"]).validate(out)


def test_assess_beneficiary_produces_all_three_verdicts():
    h = TOOLS_BY_NAME["assess_beneficiary"]["handler"]
    assert h({"repair_hint": "repairable"})["repair_verdict"] == "repairable"
    assert h({"repair_hint": "unrepairable"})["repair_verdict"] == "unrepairable"
    assert h({"repair_hint": "needs_info"})["repair_verdict"] == "needs_info"
    # steered by reason codes too
    assert h({"reason_codes": ["AC01"]})["repair_verdict"] == "repairable"
    assert h({"reason_codes": ["AC04"]})["repair_verdict"] == "unrepairable"
    assert h({})["repair_verdict"] == "needs_info"


def test_screen_party_steering():
    h = TOOLS_BY_NAME["screen_party"]["handler"]
    assert h({"party": {"name": "SANCTIONED CO"}})["status"] == "hit"
    assert h({"party": {"name": "ACME LTD"}})["status"] == "clear"
    assert h({"hint": "needs_review"})["status"] == "needs_review"


def test_action_tools_return_wellformed_ack():
    for name in ACTION_TOOLS:
        ack = TOOLS_BY_NAME[name]["handler"]({"exception_id": "exc-1"})
        assert ack["acknowledged"] is True
        assert ack["action_id"].startswith("act-")
        assert ack["status"] in ("performed", "queued", "rejected")


def test_determinism_same_input_same_output():
    for t in TOOLS:
        inp = REP[t["name"]]
        assert t["handler"](inp) == t["handler"](inp)
    # action_id is a stable function of exception_id + tool, and varies by exception.
    apply = TOOLS_BY_NAME["apply_repair"]["handler"]
    assert apply({"exception_id": "exc-42"})["action_id"] == apply({"exception_id": "exc-42"})["action_id"]
    assert apply({"exception_id": "exc-42"})["action_id"] != apply({"exception_id": "exc-99"})["action_id"]


# --------------------------------------------------------------------------- #
# SDK transport (in-memory) — proves tools/list + structured tools/call.
# --------------------------------------------------------------------------- #

async def test_sdk_tools_list_and_structured_call():
    pytest.importorskip("mcp")
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    from wire_transfer_exception_mcp.server import build_server

    async with connect(build_server()) as client:
        listed = await client.list_tools()
        assert len(listed.tools) == 10
        assert {t.name for t in listed.tools} == EXPECTED_TOOLS
        for tool in listed.tools:
            assert (tool.inputSchema or {}).get("type") == "object"
            assert (tool.outputSchema or {}).get("type") == "object"

        result = await client.call_tool("assess_beneficiary", {"repair_hint": "unrepairable"})
        assert result.structuredContent["repair_verdict"] == "unrepairable"

        ack = await client.call_tool("apply_repair", {"exception_id": "exc-7"})
        assert ack.structuredContent["acknowledged"] is True
        assert ack.structuredContent["action_id"].startswith("act-")
