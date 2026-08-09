"""Schema / compliance / determinism tests for the ACH-exposure CLOSEOUT-segment MCP server (offline)."""
from __future__ import annotations

from jsonschema import Draft202012Validator

from ach_closeout_mcp.handlers import ACTION_TOOLS, TOOLS, TOOLS_BY_NAME, check_compliance

EXPECTED_TOOLS = {"verify_disposition", "mark_completed", "purge_working_data", "notify_pega"}

REP = {
    "verify_disposition": {"case_id": "case-1", "instruction": "purge"},
    "mark_completed": {"case_id": "case-1"},
    "purge_working_data": {"case_id": "case-1"},
    "notify_pega": {"case_id": "case-1", "segment": "C", "event": "CaseClosed", "result": {"ok": True}},
}


def test_expected_tool_set():
    assert {t["name"] for t in TOOLS} == EXPECTED_TOOLS
    assert len(TOOLS) == 4


def test_compliance_self_check_passes():
    check_compliance()
    for t in TOOLS:
        assert t["input_schema"]["type"] == "object"
        assert t["input_schema"].get("additionalProperties") is False
        assert t["output_schema"]["type"] == "object"


def test_every_handler_output_validates_against_its_output_schema():
    for name, args in REP.items():
        out = TOOLS_BY_NAME[name]["handler"](args)
        Draft202012Validator(TOOLS_BY_NAME[name]["output_schema"]).validate(out)


def test_action_tools_carry_the_ack_floor():
    assert ACTION_TOOLS == {"mark_completed", "purge_working_data", "notify_pega"}
    for name in ACTION_TOOLS:
        out = TOOLS_BY_NAME[name]["handler"](REP[name])
        assert {"acknowledged", "action_id", "status"} <= out.keys()
        assert out["status"] in {"performed", "queued", "rejected"}


def test_verify_disposition_maps_instruction_to_disposition():
    assert TOOLS_BY_NAME["verify_disposition"]["handler"]({"instruction": "purge"})["disposition"] == "purged"
    assert TOOLS_BY_NAME["verify_disposition"]["handler"]({"instruction": "release"})["disposition"] == "released"


def test_handlers_are_deterministic():
    for name, args in REP.items():
        assert TOOLS_BY_NAME[name]["handler"](args) == TOOLS_BY_NAME[name]["handler"](dict(args))
