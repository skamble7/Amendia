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
    DeclareTriggerRequest,
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
from app.services.inference import refine_input_sources, suggest_binding_input_map
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


def test_auto_fill_is_a_per_field_composite_over_declared_fields_never_whole():
    # ADR-052: an MCP capability's input_map is ALWAYS a per-field composite over its declared input fields —
    # ticket_id name-matches the declared trigger; `order` a same-named upstream output (ADR-050 — e.g. an order
    # declared on Task_TakeOrder); `hint` is neither → left unmapped. Never a whole {from:trigger}, and the key
    # set is always ⊆ the tool's declared input properties (so it can't overflow a closed tool schema).
    in_fields = ["order", "ticket_id", "hint"]
    trigger_fields = {"ticket_id", "order_type", "table"}
    ups = [("order", {"lines"})]                      # an upstream output NAMED `order` (Task_TakeOrder's output)
    m = suggest_binding_input_map("a_in", in_fields, ups, trigger_fields=trigger_fields)
    assert m != {"a_in": {"from": "trigger"}}         # never a whole-trigger spread
    fields = m["a_in"]["fields"]
    assert fields["ticket_id"] == {"from": "trigger", "path": "ticket_id"}
    assert fields["order"] == {"from": "artifact", "name": "order"}
    assert "hint" not in fields                       # neither upstream nor trigger → unmapped
    assert set(fields) <= set(in_fields)              # arg keys ⊆ declared tool inputs → can never overflow


def test_entry_task_builds_a_per_field_composite_never_whole_trigger():
    # ADR-052: an entry task builds a PER-FIELD composite over the tool's declared inputs (never a whole-trigger
    # spread). With NO declared trigger, `party` name-matches neither an upstream output nor a trigger field →
    # it is left UNMAPPED (not defaulted to a trigger path that would resolve to null at runtime).
    d = refine_input_sources(_draft(_ENRICH_B.model_copy(deep=True)), _CAPS, _ARTS)
    assert d.bindings[0].suggested_input_source == {"enrich_input": {"fields": {}}}


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


def test_undeclared_trigger_leaves_non_upstream_fields_unmapped():
    # ADR-052: with NO declared trigger schema, only fields matched to an UPSTREAM output are sourced; a field
    # that matches neither an upstream output nor a declared trigger field is LEFT UNMAPPED (never defaulted to
    # a trigger path — that would resolve to null and a closed tool schema rejects the null).
    d = refine_input_sources(_draft(_ENRICH_B.model_copy(deep=True), _ASSESS_B.model_copy(deep=True)),
                             _CAPS, _ARTS)  # trigger_fields=None → opaque
    fields = next(b for b in d.bindings if b.element_id == "Assess").suggested_input_source["assess_input"]["fields"]
    assert fields == {"dossier": {"from": "artifact", "name": "enrich_output", "path": "dossier"}}
    assert "exception_id" not in fields and "reason_codes" not in fields   # no declared trigger → unmapped


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
    # ADR-052: the capability resolves off the token match → a per-field composite; `p` matches neither an
    # upstream output nor a declared trigger (none here) → unmapped. The point is the capability RESOLVED.
    assert d.bindings[0].suggested_input_source == {"in": {"fields": {}}}


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
    # ADR-052: declare the trigger so its fields drive the per-field name-match (else nothing trigger-sourced).
    s = await svc.declare_trigger(s.session_id, DeclareTriggerRequest(
        artifact_key="art.payment.exc", title="exc", json_schema={
            "type": "object", "required": ["exception_id"], "additionalProperties": False,
            "properties": {"exception_id": {"type": "string"}, "reason_codes": {"type": "array", "items": {"type": "string"}}}}),
        owner=OWNER)

    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(
        tools=[_ENRICH_TOOL, _ASSESS_TOOL]), owner=OWNER)
    # …and is upgraded to a field-level input_map once the tool schemas exist.
    enrich = next(b for b in s.inferred.bindings if b.element_id == "Enrich")
    assess = next(b for b in s.inferred.bindings if b.element_id == "Assess")
    # ADR-052: the entry task is a PER-FIELD composite. `party` matches neither an upstream output nor a declared
    # trigger field → left UNMAPPED (never defaulted to a null-resolving trigger path).
    assert enrich.suggested_input_source == {"enrich_input": {"fields": {}}}
    fields = assess.suggested_input_source["assess_input"]["fields"]
    assert fields["dossier"] == {"from": "artifact", "name": "enrich_output", "path": "dossier"}
    assert fields["exception_id"] == {"from": "trigger", "path": "exception_id"}   # declared trigger field
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
        StagedTriageRule(rule_id="r", priority=1, when={"field": "reason_codes", "op": "intersects", "value": ["AC01"]})]),
        owner=OWNER)
    s = await svc.set_policies(s.session_id, SetPoliciesRequest(), owner=OWNER)
    s = await svc.assemble(s.session_id, owner=OWNER)
    errs = [f for f in s.dry_run_report["findings"] if f["severity"] == "error"]
    assert errs == [], errs

    # the composed manifest binding carries the field-level input_map (no manual authoring).
    manifest, _descs, _regs = svc._compose(s)
    by_el = {b.element_id: b for b in manifest.bindings}
    assert by_el["Enrich"].input_map["enrich_input"].model_dump(by_alias=True, exclude_none=True) \
        == {"fields": {}}
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
    s = await svc.declare_trigger(s.session_id, DeclareTriggerRequest(
        artifact_key="art.payment.exc", title="exc", json_schema={
            "type": "object", "required": ["exception_id"], "additionalProperties": False,
            "properties": {"exception_id": {"type": "string"}, "reason_codes": {"type": "array", "items": {"type": "string"}}}}),
        owner=OWNER)
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
    # ADR-052: entry → per-field composite. `party` is neither an upstream output nor a declared trigger field →
    # left unmapped (never a null-resolving trigger path). The point is the map derives off the BOUND capability.
    assert inv.input_sources == {"enrich_investigation_input": {"fields": {}}}
    fields = ev.input_sources["assess_beneficiary_input"]["fields"]
    assert fields["dossier"] == {"from": "artifact", "name": "enrich_investigation_output", "path": "dossier"}
    assert fields["exception_id"] == {"from": "trigger", "path": "exception_id"}
    assert fields["reason_codes"] == {"from": "trigger", "path": "reason_codes"}

    s = await svc.set_triage(s.session_id, SetTriageRequest(triage_rules=[
        StagedTriageRule(rule_id="r", priority=1, when={"field": "reason_codes", "op": "intersects", "value": ["AC01"]})]),
        owner=OWNER)
    s = await svc.set_policies(s.session_id, SetPoliciesRequest(), owner=OWNER)
    s = await svc.assemble(s.session_id, owner=OWNER)
    unproduced = [f for f in s.dry_run_report["findings"] if f["code"] == "unproduced_input"]
    assert unproduced == [], unproduced                                    # zero, with no manual authoring


# start → GetMenu(entry, serviceTask) → End — an MCP capability whose declared input fields overlap the trigger.
_MENU_BPMN = f"""<bpmn:definitions {_NS}>
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="GetMenu" name="Present menu"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="GetMenu"/>
    <bpmn:sequenceFlow id="f2" sourceRef="GetMenu" targetRef="E"/>
  </bpmn:process>
</bpmn:definitions>"""

_MENU_TOOL = CapabilityToolSelection(
    tool="get_menu", endpoint="http://mcp.local/mcp",
    input_schema={"type": "object", "additionalProperties": False,
                  "properties": {"request": {"type": "string"}, "ticket_id": {"type": "string"}, "tender": {"type": "string"}}},
    output_schema={"type": "object", "properties": {"menu": {"type": "object"}}, "required": ["menu"]},
    side_effect="read_only", idempotent=True)

_ORDER_TRIGGER = {"type": "object", "required": ["ticket_id", "order_type"], "additionalProperties": False,
                  "properties": {"ticket_id": {"type": "string"}, "order_type": {"type": "string"},
                                 "tender": {"type": "string"}}}


async def test_mcp_input_name_matches_declared_trigger_fields_not_deployment_samples(svc):
    # ADR-052 Part 2: with a DECLARED trigger (art.dining.order_ticket) an MCP capability whose input declares
    # `ticket_id` + `tender` MUST match them to trigger paths — NOT yield {} because the deployment's foreign
    # (wire) sample fields don't overlap the dining inputs. `request` (not a trigger field) is left unmapped.
    s = await svc.create(CreateSessionRequest(pack_key="dinein", version="1.0.0", title="t",
                                              default_domain="dining"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=_MENU_BPMN), owner=OWNER)
    s = await svc.declare_trigger(s.session_id, DeclareTriggerRequest(
        artifact_key="art.dining.order_ticket", title="ticket", json_schema=_ORDER_TRIGGER), owner=OWNER)
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(tools=[_MENU_TOOL]), owner=OWNER)
    s = await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=[
        BindingInput(element_id="GetMenu", element_kind="serviceTask", executor_type="capability",
                     capability_ref="cap.dining.get_menu@^1.0.0", hitl_mode="none")]), owner=OWNER)
    gm = next(b for b in s.bindings if b.element_id == "GetMenu")
    assert gm.input_sources == {"get_menu_input": {"fields": {
        "ticket_id": {"from": "trigger", "path": "ticket_id"},
        "tender": {"from": "trigger", "path": "tender"},
    }}}                                                            # non-empty; `request` unmapped (not a trigger field)


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
