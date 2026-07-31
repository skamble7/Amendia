# tests/test_copilot_generate.py
"""ADR-052 Phase 2a — the onboarding copilot generation core.

Golden acceptance is the restaurant: the dine-in BPMN + the dinein MCP tool schemas (fake introspection) + a
recorded CopilotProposal (fake LLM, no network) must produce a populated, VALIDATOR-CLEAN draft session
equivalent to the hand-built rest-stan pack. Plus: the deterministic side-effect floor is enforced regardless
of the LLM, human-authored artifacts are derived from the consuming tool input shape, and the repair loop
recovers a bad proposal.
"""
from __future__ import annotations

import json

import pytest

from app.models.onboarding import CopilotGenerateRequest, CopilotMcpConfig
from app.services.copilot import llm as copilot_llm
from app.services.copilot.service import CopilotService
from app.services.onboarding import OnboardingService
from tests._restaurant_copilot import (
    FakeLLMClient,
    restaurant_bpmn,
    restaurant_proposal_json,
    restaurant_tools,
    restaurant_trigger,
    restaurant_triage,
)
from tests.conftest import FakeMcpIntrospector

OWNER = "usr-owner"


@pytest.fixture
def copilot_svc(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo):
    # The copilot handles comprehensive diagrams → the executable profile (boundary timers, loops, etc.).
    svc = OnboardingService(
        onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
        FakeMcpIntrospector(restaurant_tools()), sample_envelopes=[], profile="common_executable")
    return CopilotService(svc)


def _req(**over):
    body = {"pack_key": "rest-stan", "version": "1.0.0", "title": "Restaurant dine-in",
            "bpmn_xml": restaurant_bpmn(), "trigger": restaurant_trigger(), "triage_rules": restaurant_triage(),
            "mcp": CopilotMcpConfig(endpoint="http://dinein-mcp:8070/mcp")}
    body.update(over)
    return CopilotGenerateRequest(**body)


def _fake_llm(monkeypatch, *responses):
    fake = FakeLLMClient(list(responses))
    monkeypatch.setattr(copilot_llm, "_llm_client", lambda ref: fake)
    return fake


def _binding(session, element_id):
    return next((b for b in session.bindings if b.element_id == element_id), None)


async def test_restaurant_generates_a_validator_clean_pack(copilot_svc, monkeypatch):
    _fake_llm(monkeypatch, restaurant_proposal_json())
    session = await copilot_svc.generate(_req(), owner=OWNER)

    # --- the assembled draft PASSES the 7-stage validator ---
    errors = [f for f in (session.dry_run_report or {}).get("findings", []) if f["severity"] == "error"]
    assert errors == [], errors
    assert session.state.value == "assembled"

    # --- element → tool bindings ---
    assert _binding(session, "Task_PresentMenu").capability_ref.startswith("cap.rest_stan.get_menu@")
    assert _binding(session, "Task_ValidateOrder").capability_ref.startswith("cap.rest_stan.validate_order@")
    assert _binding(session, "Task_ScreenAllergens").capability_ref.startswith("cap.rest_stan.screen_allergens@")
    assert _binding(session, "Task_GenerateBill").capability_ref.startswith("cap.rest_stan.generate_bill@")
    assert _binding(session, "Task_FireTicket").capability_ref.startswith("cap.rest_stan.fire_ticket@")
    assert _binding(session, "Task_ProcessPayment").capability_ref.startswith("cap.rest_stan.charge_payment@")
    # SelectItems is a human authoring `order`; ProcessPayment is charge_payment
    sel = _binding(session, "Task_SelectItems")
    assert sel.executor_type == "human"
    assert [o.name for o in sel.outputs] == ["order"]

    # --- output names align to the gateways (validation / allergen / receipt) so the gateways branch ---
    assert _binding(session, "Task_ValidateOrder").outputs[0].name == "validation"
    assert _binding(session, "Task_ScreenAllergens").outputs[0].name == "allergen"
    assert _binding(session, "Task_ProcessPayment").outputs[0].name == "receipt"

    # --- input maps ---
    vmap = _binding(session, "Task_ValidateOrder").input_sources["validate_order_input"]["fields"]
    assert vmap["order"] == {"from": "artifact", "name": "order"}
    smap = _binding(session, "Task_ScreenAllergens").input_sources["screen_allergens_input"]["fields"]
    assert smap["dietary_flags"] == {"from": "trigger", "path": "dietary_flags"}
    pmap = _binding(session, "Task_ProcessPayment").input_sources["charge_payment_input"]["fields"]
    assert pmap["tender"] == {"from": "artifact", "name": "payment", "path": "tender"}
    # SelectItems reads `menu` (read-only) from get_menu_output
    assert sel.input_sources["menu"] == {"from": "artifact", "name": "get_menu_output"}

    # --- human-authored `art.rest_stan.order` derived from the consuming tools' input shape + registered ---
    order_art = next(a for a in session.authored_artifacts if a.artifact_key == "art.rest_stan.order")
    js = order_art.json_schema
    assert js["type"] == "object" and js["additionalProperties"] is False
    assert list(js["properties"]) == ["items"] and js["properties"]["items"]["type"] == "array"
    assert js["required"] == ["items"]           # only the field the tools consume — nothing invented
    # payment derived from charge_payment.tender (a scalar path)
    pay_art = next(a for a in session.authored_artifacts if a.artifact_key == "art.rest_stan.payment")
    assert list(pay_art.json_schema["properties"]) == ["tender"]

    # --- the report: plain-language summary + provenance + open questions ---
    rep = session.copilot_report
    assert rep is not None and rep.summary and rep.llm_used and rep.repair_passes == 0
    assert any(d.decided_by == "llm" for d in rep.decisions)
    assert any(d.decided_by == "deterministic" for d in rep.decisions)


async def test_guaranteed_upstream_inputs_stay_required_no_loopback_regression(copilot_svc, monkeypatch):
    # Loop-back optionality (ADR-052) must NOT touch inputs whose producer is a guaranteed upstream predecessor.
    # In the restaurant, `order` (SelectItems dominates ValidateOrder) and `payment` (PresentPayment dominates
    # ProcessPayment) are guaranteed → they stay REQUIRED (no `optional` flag), even though the diagram has revise
    # and payment-retry loops. Trigger-sourced inputs are never optional.
    _fake_llm(monkeypatch, restaurant_proposal_json())
    session = await copilot_svc.generate(_req(), owner=OWNER)

    vmap = _binding(session, "Task_ValidateOrder").input_sources["validate_order_input"]["fields"]
    assert vmap["order"] == {"from": "artifact", "name": "order"}          # guaranteed → no optional key
    pmap = _binding(session, "Task_ProcessPayment").input_sources["charge_payment_input"]["fields"]
    assert pmap["tender"] == {"from": "artifact", "name": "payment", "path": "tender"}
    smap = _binding(session, "Task_ScreenAllergens").input_sources["screen_allergens_input"]["fields"]
    assert "optional" not in smap["dietary_flags"]                          # trigger source → never optional
    # nothing in a linear-producer pack should have been marked optional
    for b in session.bindings:
        for comp in (b.input_sources or {}).values():
            for src in (comp.get("fields", {}) if isinstance(comp, dict) else {}).values():
                assert not (isinstance(src, dict) and src.get("optional")), (b.element_id, src)


async def test_rederived_changed_schema_bumps_the_version_and_references_it(copilot_svc, schema_repo, monkeypatch):
    # ADR-052 Part 3: a prior onboarding registered art.rest_stan.order@1.0.0 with a DIFFERENT schema. This onboarding
    # re-derives a different shape → it must register at a bumped minor (1.1.0) and reference it, so a same-domain
    # re-onboard adopts the improvement instead of silently reusing the stale (immutable) 1.0.0 registration.
    from amendia_contracts.artifact_schema import ArtifactSchemaRegistration, ArtifactStatus
    await schema_repo.insert(ArtifactSchemaRegistration(
        artifact_key="art.rest_stan.order", version="1.0.0", title="Order",
        json_schema={"type": "object", "additionalProperties": False,
                     "properties": {"stale_field": {"type": "string"}}, "required": ["stale_field"]},
        status=ArtifactStatus.ACTIVE))
    _fake_llm(monkeypatch, restaurant_proposal_json())
    session = await copilot_svc.generate(_req(), owner=OWNER)

    order = next(a for a in session.authored_artifacts if a.artifact_key == "art.rest_stan.order")
    assert order.version == "1.1.0"                                          # bumped — schema changed
    assert _binding(session, "Task_SelectItems").outputs[0].schema_ref == "art.rest_stan.order@^1.1.0"
    # payment wasn't pre-registered → a fresh key stays 1.0.0 (no gratuitous bump)
    pay = next(a for a in session.authored_artifacts if a.artifact_key == "art.rest_stan.payment")
    assert pay.version == "1.0.0"
    assert [f for f in (session.dry_run_report or {}).get("findings", []) if f["severity"] == "error"] == []


async def test_rederived_unchanged_schema_does_not_churn_the_version(copilot_svc, schema_repo, monkeypatch):
    # Pre-register the EXACT schema the copilot derives for art.rest_stan.order → reuse 1.0.0 (unchanged ⇒ no bump).
    from amendia_contracts.artifact_schema import ArtifactSchemaRegistration, ArtifactStatus
    derived = {"type": "object", "additionalProperties": False,
               "properties": {"items": {"type": "array", "items": {"type": "string"}}}, "required": ["items"],
               "$schema": "https://json-schema.org/draft/2020-12/schema"}
    await schema_repo.insert(ArtifactSchemaRegistration(
        artifact_key="art.rest_stan.order", version="1.0.0", title="Order", json_schema=derived,
        status=ArtifactStatus.ACTIVE))
    _fake_llm(monkeypatch, restaurant_proposal_json())
    session = await copilot_svc.generate(_req(), owner=OWNER)

    order = next(a for a in session.authored_artifacts if a.artifact_key == "art.rest_stan.order")
    assert order.version == "1.0.0"                                          # identical → reuse, no churn
    assert _binding(session, "Task_SelectItems").outputs[0].schema_ref == "art.rest_stan.order@^1.0.0"


async def test_side_effect_floor_is_enforced_even_when_the_llm_proposes_weaker(copilot_svc, monkeypatch):
    # The fake LLM proposes fire_ticket with HITL `none` and charge_payment with `review_after` — both too weak
    # for a side-effectful tool. Reconciliation MUST clamp both up to approve_actions (deterministic wins).
    _fake_llm(monkeypatch, restaurant_proposal_json(fire_hitl="none", process_hitl="review_after"))
    session = await copilot_svc.generate(_req(), owner=OWNER)

    assert _binding(session, "Task_FireTicket").hitl_mode == "approve_actions"
    assert _binding(session, "Task_ProcessPayment").hitl_mode == "approve_actions"
    # a clamp is recorded as a deterministic correction in the provenance
    clamps = [d for d in session.copilot_report.decisions if d.kind == "hitl" and d.decided_by == "deterministic"]
    assert any("Task_FireTicket" == d.element_id for d in clamps)
    # still validator-clean
    errors = [f for f in (session.dry_run_report or {}).get("findings", []) if f["severity"] == "error"]
    assert errors == [], errors


async def test_repair_loop_recovers_a_bad_proposal(copilot_svc, monkeypatch):
    # First proposal binds Task_ValidateOrder to the WRONG tool (get_menu) → a validator error. The repair loop
    # re-calls the LLM (second recorded response is the correct proposal) and converges to a clean validate.
    bad = json.loads(restaurant_proposal_json())
    for e in bad["elements"]:
        if e["element_id"] == "Task_ValidateOrder":
            e["executor"]["capability_tool"] = "get_menu"      # wrong tool → gateway/output misalignment
            e["output_name"] = "validation"
    fake = _fake_llm(monkeypatch, json.dumps(bad), restaurant_proposal_json())

    session = await copilot_svc.generate(_req(), owner=OWNER)

    errors = [f for f in (session.dry_run_report or {}).get("findings", []) if f["severity"] == "error"]
    assert errors == [], errors
    assert session.copilot_report.repair_passes >= 1
    assert len(fake.calls) >= 2                                # the repair re-called the LLM
    assert _binding(session, "Task_ValidateOrder").capability_ref.startswith("cap.rest_stan.validate_order@")


async def test_disabled_llm_surfaces_a_clear_error(copilot_svc, monkeypatch):
    monkeypatch.setattr(copilot_llm.settings, "COPILOT_LLM_DISABLED", True)
    with pytest.raises(copilot_llm.CopilotLLMError):
        await copilot_svc.generate(_req(), owner=OWNER)


_VALID_OPS = {"eq", "ne", "in", "starts_with", "intersects", "exists", "gt", "gte", "lt", "lte"}


async def test_user_triage_is_applied_verbatim(copilot_svc, monkeypatch):
    # Triage is USER-PROVIDED (not inferred): the operator's predicate reaches the pack unchanged.
    _fake_llm(monkeypatch, restaurant_proposal_json())
    session = await copilot_svc.generate(_req(triage_rules=[
        {"rule_id": "dine_in", "priority": 100, "when": {"field": "order_type", "op": "eq", "value": "dine_in"}}]),
        owner=OWNER)

    errors = [f for f in (session.dry_run_report or {}).get("findings", []) if f["severity"] == "error"]
    assert errors == [], errors
    assert [r.rule_id for r in session.triage_rules] == ["dine_in"]
    assert session.triage_rules[0].when == {"field": "order_type", "op": "eq", "value": "dine_in"}


async def test_user_triage_synonym_op_is_normalized_as_a_safety_net(copilot_svc, monkeypatch):
    # The predicate sanitation still runs on the user's rules as a safety net: a synonym op (not_empty) normalizes
    # to `exists`; an invalid op alongside is dropped + surfaced, while the valid rule keeps the pack assemblable.
    _fake_llm(monkeypatch, restaurant_proposal_json())
    session = await copilot_svc.generate(_req(triage_rules=[
        {"rule_id": "dine_in", "priority": 100, "when": {"field": "order_type", "op": "eq", "value": "dine_in"}},
        {"rule_id": "has_diet", "priority": 100, "when": {"field": "dietary_flags", "op": "not_empty", "value": None}},
        {"rule_id": "broken", "priority": 100, "when": {"field": "order_type", "op": "fuzzy_match", "value": "x"}}]),
        owner=OWNER)

    errors = [f for f in (session.dry_run_report or {}).get("findings", []) if f["severity"] == "error"]
    assert errors == [], errors
    by_id = {r.rule_id: r for r in session.triage_rules}
    assert by_id["has_diet"].when == {"field": "dietary_flags", "op": "exists"}   # synonym normalized, null dropped
    assert "broken" not in by_id                                                  # invalid op dropped
    assert all(r.when.get("op") in _VALID_OPS or "any" in r.when or "all" in r.when for r in session.triage_rules)
    assert any("broken" in (q.question or "") for q in session.copilot_report.open_questions)


async def test_user_trigger_is_registered_and_grounds_input_map(copilot_svc, monkeypatch):
    # The trigger is USER-PROVIDED (a sample event here) → registered as the pack's trigger artifact, and a
    # trigger-sourced input_map field grounds on the schema's REAL top-level path (dietary_flags), not a guess.
    _fake_llm(monkeypatch, restaurant_proposal_json())
    session = await copilot_svc.generate(_req(), owner=OWNER)

    assert session.trigger_artifact is not None
    ts = session.trigger_artifact.json_schema
    assert "dietary_flags" in ts["properties"] and "order_type" in ts["properties"]   # derived from the user's sample
    smap = _binding(session, "Task_ScreenAllergens").input_sources["screen_allergens_input"]["fields"]
    assert smap["dietary_flags"] == {"from": "trigger", "path": "dietary_flags"}
    assert any(d.kind == "trigger" and d.decided_by == "user" for d in session.copilot_report.decisions)


async def test_over_map_guard_drops_a_field_the_tool_does_not_declare(copilot_svc, monkeypatch):
    # The LLM over-maps: it adds `bill` to validate_order, whose closed input schema declares only order/ticket_id/
    # hint. The guard drops the undeclared field (so no runtime MCP_TOOL_ERROR), maps only declared fields, and
    # records it in provenance. (Deterministic disposes, exactly like the HITL clamp.)
    p = json.loads(restaurant_proposal_json())
    for e in p["elements"]:
        if e["element_id"] == "Task_ValidateOrder":
            e["input_map"].append({"field": "bill", "from": "artifact", "name": "order"})
    _fake_llm(monkeypatch, json.dumps(p))
    session = await copilot_svc.generate(_req(), owner=OWNER)

    errors = [f for f in (session.dry_run_report or {}).get("findings", []) if f["severity"] == "error"]
    assert errors == [], errors
    fields = _binding(session, "Task_ValidateOrder").input_sources["validate_order_input"]["fields"]
    assert "order" in fields and "bill" not in fields          # only tool-declared fields reach the pack
    assert any("bill" in d.summary and d.decided_by == "deterministic"
               for d in session.copilot_report.decisions)


async def test_generate_degrades_instead_of_422_when_a_transition_rejects_content(copilot_svc, monkeypatch):
    # Belt-and-suspenders: even if a strict transition rejects proposal content the sanitizer couldn't fix,
    # generate returns a reviewable DEGRADED draft + open question — never a bubbled 422 (502 is reserved for an
    # unreachable model). Force set_triage to always reject to exercise the service-level wrap.
    from app.services.onboarding import TransitionError

    _fake_llm(monkeypatch, restaurant_proposal_json())

    async def always_reject(*_a, **_k):
        raise TransitionError(422, {"error": "triage_invalid", "errors": [{"message": "simulated rejection"}]})

    monkeypatch.setattr(copilot_svc._svc, "set_triage", always_reject)
    session = await copilot_svc.generate(_req(), owner=OWNER)             # must NOT raise

    assert session.copilot_report is not None
    assert any(q.topic == "content" for q in session.copilot_report.open_questions)
