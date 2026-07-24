# tests/test_input_map_inference.py
"""ADR-048 D4 — FIELD-LEVEL input-source inference. Once the tool schemas are staged, the wizard should
pre-fill each capability task's whole input_map (not a one-key hint): an entry task from the trigger, a
downstream task's input fields matched to upstream output fields or trigger paths. The operator confirms a
suggestion instead of authoring each source. Domain-neutral — field names come from the tool schemas.
"""
import pytest

from app.models.onboarding import (
    AttachBpmnRequest,
    BindingInput,
    CapabilityToolSelection,
    CreateSessionRequest,
    InferenceDraft,
    InferredBinding,
    SetBindingsRequest,
    SetCapabilitiesRequest,
    SetPoliciesRequest,
    SetTriageRequest,
    StagedArtifact,
    StagedCapability,
    StagedTriageRule,
)
from app.services.inference import refine_input_sources
from app.services.onboarding import OnboardingService
from tests.conftest import load_sample

OWNER = "usr-owner"
_NS = 'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'


# --------------------------------------------------------------------------- #
# Unit — refine_input_sources against a hand-built draft + staged schemas
# --------------------------------------------------------------------------- #

def _cap(cid, in_name, in_key, out_name, out_key):
    return StagedCapability(capability_id=cid, version="1.0.0", title=cid,
                            input_name=in_name, input_artifact_key=in_key,
                            output_name=out_name, output_artifact_key=out_key)


def _art(key, *fields):
    return StagedArtifact(artifact_key=key, version="1.0.0", title=key,
                          json_schema={"type": "object", "properties": {f: {"type": "string"} for f in fields}})


def _draft(*bindings):
    return InferenceDraft(bindings=list(bindings))


# entry Enrich → downstream Assess; Assess.input {dossier, exception_id, reason_codes}, enrich output has dossier.
_ENRICH_B = InferredBinding(element_id="Enrich", element_kind="serviceTask", executor_type="capability",
                            suggested_capability_id="cap.d.enrich", upstream_caps=[])
_ASSESS_B = InferredBinding(element_id="Assess", element_kind="serviceTask", executor_type="capability",
                            suggested_capability_id="cap.d.assess", upstream_caps=["Enrich"])
_CAPS = [_cap("cap.d.enrich", "enrich_input", "art.d.enrich_input", "enrich_output", "art.d.enrich_output"),
         _cap("cap.d.assess", "assess_input", "art.d.assess_input", "assess_output", "art.d.assess_output")]
_ARTS = [_art("art.d.enrich_input", "party"),
         _art("art.d.enrich_output", "dossier", "score"),
         _art("art.d.assess_input", "dossier", "exception_id", "reason_codes"),
         _art("art.d.assess_output", "ok")]


def test_entry_task_sources_the_whole_trigger():
    d = refine_input_sources(_draft(_ENRICH_B.model_copy(deep=True)), _CAPS, _ARTS)
    assert d.bindings[0].suggested_input_source == {"enrich_input": {"from": "trigger"}}


def test_downstream_fields_match_upstream_output_and_trigger():
    # dossier is a field of the enrich output → artifact+path; exception_id/reason_codes are trigger scalars.
    d = refine_input_sources(_draft(_ENRICH_B.model_copy(deep=True), _ASSESS_B.model_copy(deep=True)),
                             _CAPS, _ARTS, trigger_fields={"exception_id", "reason_codes"})
    assess = next(b for b in d.bindings if b.element_id == "Assess")
    assert assess.suggested_input_source == {"assess_input": {"fields": {
        "dossier": {"from": "artifact", "name": "enrich_output", "path": "dossier"},
        "exception_id": {"from": "trigger", "path": "exception_id"},
        "reason_codes": {"from": "trigger", "path": "reason_codes"},
    }}}


def test_opaque_trigger_defaults_unmatched_field_to_a_trigger_path():
    # with NO declared trigger schema, a field with no upstream producer defaults to a trigger path (the
    # only remaining origin; the validator accepts trigger as satisfiable) — never left unmapped.
    d = refine_input_sources(_draft(_ENRICH_B.model_copy(deep=True), _ASSESS_B.model_copy(deep=True)),
                             _CAPS, _ARTS)  # trigger_fields=None → opaque
    fields = next(b for b in d.bindings if b.element_id == "Assess").suggested_input_source["assess_input"]["fields"]
    assert fields["dossier"] == {"from": "artifact", "name": "enrich_output", "path": "dossier"}
    assert fields["exception_id"] == {"from": "trigger", "path": "exception_id"}
    assert fields["reason_codes"] == {"from": "trigger", "path": "reason_codes"}


def test_known_trigger_leaves_a_truly_unmatched_field_blank():
    # when the trigger schema IS known, a field neither produced upstream nor on the trigger is left for
    # the operator (omitted) — inference does not wild-guess.
    arts = [_art("art.d.enrich_input", "party"), _art("art.d.enrich_output", "dossier"),
            _art("art.d.assess_input", "dossier", "mystery"), _art("art.d.assess_output", "ok")]
    d = refine_input_sources(_draft(_ENRICH_B.model_copy(deep=True), _ASSESS_B.model_copy(deep=True)),
                             _CAPS, arts, trigger_fields={"exception_id"})
    fields = next(b for b in d.bindings if b.element_id == "Assess").suggested_input_source["assess_input"]["fields"]
    assert "dossier" in fields and "mystery" not in fields          # unmatched-and-known-trigger → blank


def test_opaque_single_input_maps_to_the_whole_upstream_output():
    # a downstream tool whose input schema has no object properties → the whole nearest upstream output.
    arts = [_art("art.d.enrich_input", "party"), _art("art.d.enrich_output", "dossier"),
            StagedArtifact(artifact_key="art.d.assess_input", version="1.0.0", title="t",
                           json_schema={"type": "object"}),  # no properties → opaque
            _art("art.d.assess_output", "ok")]
    d = refine_input_sources(_draft(_ENRICH_B.model_copy(deep=True), _ASSESS_B.model_copy(deep=True)), _CAPS, arts)
    assert next(b for b in d.bindings if b.element_id == "Assess").suggested_input_source == {
        "assess_input": {"from": "artifact", "name": "enrich_output"}}


def test_element_to_capability_matches_by_name_tokens_when_id_differs():
    # the staged capability id (from the tool name) need not equal the inferred id (from the task name) —
    # a confident token overlap still resolves it, so the pre-fill lines up with the wizard's pre-select.
    b = InferredBinding(element_id="X", element_kind="serviceTask", executor_type="capability",
                        suggested_capability_id="cap.d.assess_party", upstream_caps=[])
    caps = [_cap("cap.d.assess_party_v2", "in", "art.d.in", "out", "art.d.out")]
    arts = [_art("art.d.in", "p"), _art("art.d.out", "o")]
    d = refine_input_sources(_draft(b), caps, arts)
    assert d.bindings[0].suggested_input_source == {"in": {"from": "trigger"}}   # matched → entry whole trigger


# --------------------------------------------------------------------------- #
# Service e2e — the suggestion pre-fills, persists through set_bindings → _compose manifest input_map
# --------------------------------------------------------------------------- #

# start → Enrich(serviceTask) → Assess(serviceTask) → End
_CHAIN_BPMN = f"""<bpmn:definitions {_NS}>
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="Enrich" name="Enrich"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:serviceTask id="Assess" name="Assess"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:endEvent id="E"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Enrich"/>
    <bpmn:sequenceFlow id="f2" sourceRef="Enrich" targetRef="Assess"/>
    <bpmn:sequenceFlow id="f3" sourceRef="Assess" targetRef="E"/>
  </bpmn:process>
</bpmn:definitions>"""

_ENRICH_TOOL = CapabilityToolSelection(
    tool="enrich", endpoint="http://mcp.local/mcp",
    input_schema={"type": "object", "properties": {"party": {"type": "string"}}, "required": ["party"]},
    output_schema={"type": "object", "properties": {"dossier": {"type": "object"}, "score": {"type": "number"}},
                   "required": ["dossier"]},
    side_effect="read_only", idempotent=True)
_ASSESS_TOOL = CapabilityToolSelection(
    tool="assess", endpoint="http://mcp.local/mcp",
    input_schema={"type": "object", "properties": {"dossier": {"type": "object"},
                                                   "exception_id": {"type": "string"},
                                                   "reason_codes": {"type": "array", "items": {"type": "string"}}},
                  "required": ["dossier"]},
    output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
    side_effect="read_only", idempotent=True)


@pytest.fixture
def svc(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo, fake_introspector):
    return OnboardingService(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
                             fake_introspector, sample_envelopes=[load_sample()], profile="common_executable")


async def test_set_capabilities_prefills_field_level_input_map_and_it_persists(svc):
    s = await svc.create(CreateSessionRequest(pack_key="imap-e2e", version="1.0.0", title="t",
                                              default_domain="payment"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=_CHAIN_BPMN), owner=OWNER)
    # at attach the hint is coarse (graph position only)
    assert next(b for b in s.inferred.bindings if b.element_id == "Assess").suggested_input_source \
        == {"from": "artifact", "element": "Enrich"}

    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(
        tools=[_ENRICH_TOOL, _ASSESS_TOOL]), owner=OWNER)
    # …and is upgraded to a field-level input_map once the tool schemas exist.
    enrich = next(b for b in s.inferred.bindings if b.element_id == "Enrich")
    assess = next(b for b in s.inferred.bindings if b.element_id == "Assess")
    assert enrich.suggested_input_source == {"enrich_input": {"from": "trigger"}}
    fields = assess.suggested_input_source["assess_input"]["fields"]
    assert fields["dossier"] == {"from": "artifact", "name": "enrich_output", "path": "dossier"}
    assert fields["exception_id"] == {"from": "trigger", "path": "exception_id"}   # opaque trigger default
    assert fields["reason_codes"] == {"from": "trigger", "path": "reason_codes"}

    # bind using the pre-filled suggestion (as the wizard would) → assemble is clean, manifest carries it.
    binds = [BindingInput(element_id="Enrich", element_kind="serviceTask", executor_type="capability",
                          capability_ref="cap.payment.enrich@^1.0.0", hitl_mode="none",
                          input_sources=enrich.suggested_input_source),
             BindingInput(element_id="Assess", element_kind="serviceTask", executor_type="capability",
                          capability_ref="cap.payment.assess@^1.0.0", hitl_mode="none",
                          input_sources=assess.suggested_input_source)]
    s = await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=binds), owner=OWNER)
    s = await svc.set_triage(s.session_id, SetTriageRequest(triage_rules=[
        StagedTriageRule(rule_id="r", priority=1, when={"field": "reason_code", "op": "eq", "value": "AC01"})]),
        owner=OWNER)
    s = await svc.set_policies(s.session_id, SetPoliciesRequest(), owner=OWNER)
    s = await svc.assemble(s.session_id, owner=OWNER)
    errs = [f for f in s.dry_run_report["findings"] if f["severity"] == "error"]
    assert errs == [], errs

    # the composed manifest binding carries the field-level input_map (no manual authoring).
    manifest, _descs, _regs = svc._compose(s)
    by_el = {b.element_id: b for b in manifest.bindings}
    assert by_el["Enrich"].input_map["enrich_input"].model_dump(by_alias=True, exclude_none=True) \
        == {"from": "trigger"}
    assess_map = by_el["Assess"].input_map["assess_input"].model_dump(by_alias=True, exclude_none=True)
    assert assess_map["fields"]["dossier"] == {"from": "artifact", "name": "enrich_output", "path": "dossier"}


# start → Investigate → Evaluate → End — element names DIVERGE from the tool ids (the ws-stan failure mode).
_DIVERGENT_BPMN = f"""<bpmn:definitions {_NS}>
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="Investigate" name="Investigate"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:serviceTask id="Evaluate" name="Evaluate"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:endEvent id="E"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Investigate"/>
    <bpmn:sequenceFlow id="f2" sourceRef="Investigate" targetRef="Evaluate"/>
    <bpmn:sequenceFlow id="f3" sourceRef="Evaluate" targetRef="E"/>
  </bpmn:process>
</bpmn:definitions>"""

_ENRICH_INV_TOOL = CapabilityToolSelection(
    tool="enrich_investigation", endpoint="http://mcp.local/mcp",
    input_schema={"type": "object", "properties": {"party": {"type": "string"}}, "required": ["party"]},
    output_schema={"type": "object", "properties": {"dossier": {"type": "object"}, "score": {"type": "number"}},
                   "required": ["dossier"]},
    side_effect="read_only", idempotent=True)
_ASSESS_BEN_TOOL = CapabilityToolSelection(
    tool="assess_beneficiary", endpoint="http://mcp.local/mcp",
    input_schema={"type": "object", "properties": {"dossier": {"type": "object"},
                                                   "exception_id": {"type": "string"},
                                                   "reason_codes": {"type": "array", "items": {"type": "string"}}},
                  "required": ["dossier"]},
    output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
    side_effect="read_only", idempotent=True)


async def test_set_bindings_fills_input_map_when_element_name_diverges_from_tool_id(svc):
    # the crux: element name != tool id, so the name-token guess fails — but the capability is BOUND, so the
    # binding-time refinement (keyed off capability_ref) still produces a full field-level input_map.
    s = await svc.create(CreateSessionRequest(pack_key="imap-div", version="1.0.0", title="t",
                                              default_domain="payment"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=_DIVERGENT_BPMN), owner=OWNER)
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(
        tools=[_ENRICH_INV_TOOL, _ASSESS_BEN_TOOL]), owner=OWNER)
    # bind WITHOUT authoring any input_sources (operator sets none) — the fill must do the work.
    binds = [BindingInput(element_id="Investigate", element_kind="serviceTask", executor_type="capability",
                          capability_ref="cap.payment.enrich_investigation@^1.0.0", hitl_mode="none"),
             BindingInput(element_id="Evaluate", element_kind="serviceTask", executor_type="capability",
                          capability_ref="cap.payment.assess_beneficiary@^1.0.0", hitl_mode="none")]
    s = await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=binds), owner=OWNER)
    inv = next(b for b in s.bindings if b.element_id == "Investigate")
    ev = next(b for b in s.bindings if b.element_id == "Evaluate")
    assert inv.input_sources == {"enrich_investigation_input": {"from": "trigger"}}          # entry
    fields = ev.input_sources["assess_beneficiary_input"]["fields"]
    assert fields["dossier"] == {"from": "artifact", "name": "enrich_investigation_output", "path": "dossier"}
    assert fields["exception_id"] == {"from": "trigger", "path": "exception_id"}
    assert fields["reason_codes"] == {"from": "trigger", "path": "reason_codes"}

    s = await svc.set_triage(s.session_id, SetTriageRequest(triage_rules=[
        StagedTriageRule(rule_id="r", priority=1, when={"field": "reason_code", "op": "eq", "value": "AC01"})]),
        owner=OWNER)
    s = await svc.set_policies(s.session_id, SetPoliciesRequest(), owner=OWNER)
    s = await svc.assemble(s.session_id, owner=OWNER)
    unproduced = [f for f in s.dry_run_report["findings"] if f["code"] == "unproduced_input"]
    assert unproduced == [], unproduced                                    # zero, with no manual authoring


async def test_set_bindings_preserves_an_operator_authored_source(svc):
    # a source the operator DID set is not clobbered by the fill.
    s = await svc.create(CreateSessionRequest(pack_key="imap-ovr", version="1.0.0", title="t",
                                              default_domain="payment"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=_DIVERGENT_BPMN), owner=OWNER)
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(
        tools=[_ENRICH_INV_TOOL, _ASSESS_BEN_TOOL]), owner=OWNER)
    override = {"assess_beneficiary_input": {"fields": {"dossier": {"from": "trigger", "path": "manual"}}}}
    binds = [BindingInput(element_id="Investigate", element_kind="serviceTask", executor_type="capability",
                          capability_ref="cap.payment.enrich_investigation@^1.0.0", hitl_mode="none"),
             BindingInput(element_id="Evaluate", element_kind="serviceTask", executor_type="capability",
                          capability_ref="cap.payment.assess_beneficiary@^1.0.0", hitl_mode="none",
                          input_sources=override)]
    s = await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=binds), owner=OWNER)
    ev = next(b for b in s.bindings if b.element_id == "Evaluate")
    assert ev.input_sources == override                                    # kept verbatim, not re-derived
