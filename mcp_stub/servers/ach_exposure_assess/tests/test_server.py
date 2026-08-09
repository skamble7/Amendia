"""Schema / compliance / determinism tests for the ACH-exposure ASSESS-segment MCP server (offline)."""
from __future__ import annotations

from jsonschema import Draft202012Validator

from ach_exposure_assess_mcp.handlers import ACTION_TOOLS, TOOLS, TOOLS_BY_NAME, check_compliance

EXPECTED_TOOLS = {
    "classify_exposure", "get_client_risk_profile", "recommend_disposition",
    "draft_underwriting_message", "notify_pega",
}

REP = {
    "classify_exposure": {"case_id": "case-1", "exposure_type": "credit", "credit_amount": 330000,
                          "credit_limit": 300000, "overage": 30000},
    "get_client_risk_profile": {"case_id": "case-1", "company": "ACME-LOGISTICS"},
    "recommend_disposition": {"case_id": "case-1", "severity": "material", "risk_tier": "low", "standing": "good"},
    "draft_underwriting_message": {"case_id": "case-1", "company": "ACME-LOGISTICS", "exposure_class": "credit",
                                   "overage": 30000, "recommendation": "APPROVE"},
    "notify_pega": {"case_id": "case-1", "segment": "A", "event": "ExposureAssessed", "result": {"ok": True}},
}


def test_expected_tool_set():
    assert {t["name"] for t in TOOLS} == EXPECTED_TOOLS
    assert len(TOOLS) == 5


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
    assert ACTION_TOOLS == {"notify_pega"}
    for name in ACTION_TOOLS:
        out = TOOLS_BY_NAME[name]["handler"](REP[name])
        assert {"acknowledged", "action_id", "status"} <= out.keys()
        assert out["status"] in {"performed", "queued", "rejected"}


def test_handlers_are_deterministic():
    for name, args in REP.items():
        assert TOOLS_BY_NAME[name]["handler"](args) == TOOLS_BY_NAME[name]["handler"](dict(args))


def test_recommendation_is_an_enum_value():
    out = TOOLS_BY_NAME["recommend_disposition"]["handler"](REP["recommend_disposition"])
    assert out["recommendation"] in {"APPROVE", "REJECT", "ROUTE_UW"}


def test_notify_pega_is_dry_when_unset(monkeypatch):
    monkeypatch.delenv("PEGA_STUB_URL", raising=False)
    out = TOOLS_BY_NAME["notify_pega"]["handler"](REP["notify_pega"])
    assert out["delivered"] is False and out["status"] == "queued"
