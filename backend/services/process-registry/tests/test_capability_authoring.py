# tests/test_capability_authoring.py
"""ADR-046 (Track 2) — author a `decision` (DMN table) or `reduce` (config) capability IN the wizard,
live-validated by the shared `amendia_bpmn.dmn` / `.reduce` checks, staged like an MCP capability with an
inferred verdict / summary artifact, bound to a businessRuleTask (decision) / serviceTask (reduce), and
activated — no pre-seeding, no code.
"""
import pytest

from app.models.onboarding import (
    AttachBpmnRequest,
    BindingInput,
    CapabilityToolSelection,
    CreateSessionRequest,
    DecisionSpec,
    OnboardingState,
    ReduceSpec,
    SetBindingsRequest,
    SetCapabilitiesRequest,
    SetPoliciesRequest,
    SetTriageRequest,
    StagedTriageRule,
)
from app.services.onboarding import OnboardingService, TransitionError
from tests.conftest import load_sample

OWNER = "usr-owner"
_NS = 'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'

_ENRICH = CapabilityToolSelection(
    tool="enrich", endpoint="http://mcp.local/mcp",
    input_schema={"type": "object", "properties": {"party": {"type": "string"}}, "required": ["party"]},
    output_schema={"type": "object", "properties": {"gpi_status": {"type": "string"}, "amount": {"type": "number"}},
                   "required": ["gpi_status", "amount"]},
    side_effect="read_only", idempotent=True)


def _decision_spec(**over):
    base = dict(
        capability_id="cap.payment.classify",
        table={"hit_policy": "FIRST",
               "inputs": [{"expression": "enriched.gpi_status", "type": "string"}],
               "outputs": [{"name": "verdict", "type": "string"}],
               "rules": [{"when": ['"ACSP"'], "then": ["auto_repair"]},
                         {"when": ['"RJCT"'], "then": ["reject"]},
                         {"when": ["-"], "then": ["manual_review"]}]},
        input_artifact_key="art.payment.enrich_output", input_name="enriched",
        output_artifact_key="art.payment.classify_verdict", output_name="classification")
    base.update(over)
    return DecisionSpec(**base)


def _reduce_spec(**over):
    base = dict(
        capability_id="cap.payment.anyhit",
        config={"op": "any", "item_path": "status", "predicate": '"hit"', "output_field": "has_hit"},
        input_artifact_key="art.payment.screening_list",
        output_artifact_key="art.payment.anyhit_summary", output_name="summary")
    base.update(over)
    return ReduceSpec(**base)


# start → Enrich(serviceTask, mcp) → Classify(businessRuleTask, decision) → End
_DMN_BPMN = f"""<bpmn:definitions {_NS}>
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="Enrich" name="Enrich"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:businessRuleTask id="Classify" name="Classify" calledDecision="D"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:businessRuleTask>
    <bpmn:endEvent id="E"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Enrich"/>
    <bpmn:sequenceFlow id="f2" sourceRef="Enrich" targetRef="Classify"/>
    <bpmn:sequenceFlow id="f3" sourceRef="Classify" targetRef="E"/>
  </bpmn:process>
</bpmn:definitions>"""


@pytest.fixture
def svc(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo, fake_introspector):
    return OnboardingService(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
                             fake_introspector, sample_envelopes=[load_sample()], profile="common_executable")


async def _new(svc, bpmn, pack_key):
    s = await svc.create(CreateSessionRequest(pack_key=pack_key, version="1.0.0", title="t"), owner=OWNER)
    return await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=bpmn), owner=OWNER)


# --- stage a decision -----------------------------------------------------------------------------

async def test_stage_decision_infers_verdict_artifact(svc):
    s = await _new(svc, _DMN_BPMN, "dmn-stage")
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(
        tools=[_ENRICH], decision_specs=[_decision_spec()]), owner=OWNER)
    dec = next(c for c in s.staged_capabilities if c.capability_id == "cap.payment.classify")
    assert dec.kind == "decision" and dec.table["hit_policy"] == "FIRST"
    verdict = next(a for a in s.staged_artifacts if a.artifact_key == "art.payment.classify_verdict")
    # each output column → a REQUIRED field (a gateway can branch on it); string literals → an enum
    assert verdict.json_schema["required"] == ["verdict"]
    assert verdict.json_schema["properties"]["verdict"]["enum"] == ["auto_repair", "reject", "manual_review"]


async def test_malformed_table_surfaces_dmn_finding_at_stage(svc):
    s = await _new(svc, _DMN_BPMN, "dmn-bad")
    bad = _decision_spec(table={"hit_policy": "NOPE", "inputs": [{"expression": "enriched.x"}],
                                "outputs": [{"name": "v"}], "rules": [{"when": ["<< bad"], "then": ["a"]}]})
    with pytest.raises(TransitionError) as ei:
        await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(tools=[_ENRICH], decision_specs=[bad]), owner=OWNER)
    codes = {e.get("code") for e in ei.value.detail["errors"]}
    assert "dmn_unknown_hit_policy" in codes and "dmn_bad_unary_test" in codes


# --- stage a reduce -------------------------------------------------------------------------------

async def test_stage_reduce_infers_summary_artifact(svc):
    s = await _new(svc, _DMN_BPMN, "red-stage")
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(
        tools=[_ENRICH], reduce_specs=[_reduce_spec()]), owner=OWNER)
    red = next(c for c in s.staged_capabilities if c.capability_id == "cap.payment.anyhit")
    assert red.kind == "reduce" and red.config["op"] == "any"
    summ = next(a for a in s.staged_artifacts if a.artifact_key == "art.payment.anyhit_summary")
    assert summ.json_schema["properties"]["has_hit"] == {"type": "boolean"}   # `any` → boolean
    assert summ.json_schema["required"] == ["has_hit"]


async def test_malformed_reduce_surfaces_finding(svc):
    s = await _new(svc, _DMN_BPMN, "red-bad")
    bad = _reduce_spec(config={"op": "wat", "output_field": "x"})
    with pytest.raises(TransitionError) as ei:
        await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(tools=[_ENRICH], reduce_specs=[bad]), owner=OWNER)
    assert "reduce_unknown_op" in {e.get("code") for e in ei.value.detail["errors"]}


# --- end-to-end: an authored decision onboards to active (no pre-seeded capability) ---------------

async def test_authored_decision_pack_onboards_to_active(svc, pack_repo, cap_repo, schema_repo):
    s = await _new(svc, _DMN_BPMN, "dmn-e2e")
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(
        tools=[_ENRICH], decision_specs=[_decision_spec()]), owner=OWNER)
    binds = [
        BindingInput(element_id="Enrich", element_kind="serviceTask", executor_type="capability",
                     capability_ref="cap.payment.enrich@^1.0.0", hitl_mode="none"),
        BindingInput(element_id="Classify", element_kind="businessRuleTask", executor_type="capability",
                     capability_ref="cap.payment.classify@^1.0.0", hitl_mode="none"),
    ]
    s = await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=binds), owner=OWNER)
    s = await svc.set_triage(s.session_id, SetTriageRequest(triage_rules=[
        StagedTriageRule(rule_id="r", priority=1, when={"field": "reason_code", "op": "eq", "value": "AC01"})]), owner=OWNER)
    s = await svc.set_policies(s.session_id, SetPoliciesRequest(), owner=OWNER)
    s = await svc.assemble(s.session_id, owner=OWNER)
    errs = [f for f in s.dry_run_report["findings"] if f["severity"] == "error"]
    assert errs == [], errs
    s = await svc.commit(s.session_id, owner=OWNER)
    assert s.state == OnboardingState.COMPLETED
    pack = await pack_repo.get("dmn-e2e", "1.0.0")
    assert pack.status.value == "active"
    # the authored decision capability was registered as a native `decision` (no pre-seeding)
    dec = await cap_repo.get("cap.payment.classify", "1.0.0")
    assert dec is not None and dec.kind.value == "decision"
    assert dec.runtime.table["outputs"][0]["name"] == "verdict"
    # its inferred verdict artifact is registered + the field is required (gateway-branchable)
    verdict = await schema_repo.get("art.payment.classify_verdict", "1.0.0")
    assert verdict.json_schema["required"] == ["verdict"]
    # re-commit is a no-op
    s2 = await svc.commit(s.session_id, owner=OWNER)
    assert s2.state == OnboardingState.COMPLETED
