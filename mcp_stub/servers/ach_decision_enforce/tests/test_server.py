"""Schema / compliance / determinism tests for the ACH-exposure ENFORCE-segment MCP server (offline)."""
from __future__ import annotations

from jsonschema import Draft202012Validator

from ach_decision_enforce_mcp.handlers import ACTION_TOOLS, TOOLS, TOOLS_BY_NAME, check_compliance

EXPECTED_TOOLS = {"capture_decision", "prepare_release", "request_purge", "notify_pega"}

REP = {
    "capture_decision": {"case_id": "case-1", "rbo_decision": "approve", "underwriter": "u@flagstar.com"},
    "prepare_release": {"case_id": "case-1", "records": ["r1", "r2"]},
    "request_purge": {"case_id": "case-1", "reason": "rejected"},
    "notify_pega": {"case_id": "case-1", "segment": "B", "event": "DecisionEnforced", "result": {"ok": True}},
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
    assert ACTION_TOOLS == {"prepare_release", "request_purge", "notify_pega"}
    for name in ACTION_TOOLS:
        out = TOOLS_BY_NAME[name]["handler"](REP[name])
        assert {"acknowledged", "action_id", "status"} <= out.keys()
        assert out["status"] in {"performed", "queued", "rejected"}


def test_capture_decision_rbo_is_the_gateway_key_enum():
    # The Segment-B gateway branches on decision.rbo_decision — it is required + enum(approve/reject).
    out_schema = TOOLS_BY_NAME["capture_decision"]["output_schema"]
    assert out_schema["properties"]["rbo_decision"]["enum"] == ["approve", "reject"]
    assert "rbo_decision" in out_schema["required"]
    assert TOOLS_BY_NAME["capture_decision"]["handler"](REP["capture_decision"])["rbo_decision"] == "approve"
    # unknown/absent decision falls back to the safe gateway default "reject"
    assert TOOLS_BY_NAME["capture_decision"]["handler"]({"case_id": "c"})["rbo_decision"] == "reject"


def test_handlers_are_deterministic():
    for name, args in REP.items():
        assert TOOLS_BY_NAME[name]["handler"](args) == TOOLS_BY_NAME[name]["handler"](dict(args))
