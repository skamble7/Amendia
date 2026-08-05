# tests/test_copilot_human_artifacts_and_gates.py
"""ADR-052 Parts C & D — deterministic reconcile fixes (no LLM, no network).

C — a human-authored artifact's schema is derived from the CONSUMING tools' input shapes; it must carry concrete
typed properties (so the HITL Form renders real fields, not Raw JSON) and UNION every consumer's expectations (one
step reads the whole object, another reads X.field by path → all referenced fields exist). An opaque consumer is an
inherent limit, but a well-typed input is never stripped to a bare object.

D — a HITL gate is a HUMAN authorization; its role must be a human lane, never the automation/AI lane that executes
the step. reconcile detects the automation lane structurally (a lane whose bindable members are all capability
tasks) and reassigns a gate carrying its role to the pack's human approver (or raises an open question).
"""
from __future__ import annotations

from types import SimpleNamespace

from app.models.onboarding import (
    CopilotMcpConfig,
    InferenceDraft,
    InferredBinding,
    InferredRole,
    IntrospectedTool,
    IntrospectMcpResponse,
    SodCandidate,
    ToolCompliance,
)
from app.services.copilot.flowgraph import FlowGraph
from app.services.copilot.reconcile import ApprovalGate, detect_approval_gates
from app.services.copilot.proposal import (
    CopilotProposal,
    ElementProposal,
    ExecutorProposal,
    HitlProposal,
    InputMapProposal,
    OutputFieldProposal,
    OutputProposal,
    ReadOnlyInputProposal,
)
from app.services.copilot.reconcile import Reconciler


def _tool(name: str, props: dict, side_effect: str = "pure") -> IntrospectedTool:
    return IntrospectedTool(
        name=name, description=name,
        input_schema={"type": "object", "additionalProperties": False, "properties": props},
        output_schema={"type": "object"}, compliance=ToolCompliance(compliant=True),
        suggested_side_effect=side_effect)


def _reconciler(proposal: CopilotProposal, tools: list) -> Reconciler:
    return Reconciler(
        svc=None, domain="payment", mcp=CopilotMcpConfig(endpoint="http://wirefix-mcp:8060/mcp"),
        tools=IntrospectMcpResponse(endpoint="http://wirefix-mcp:8060/mcp", transport="streamable_http", tools=tools),
        proposal=proposal, owner="usr-owner")


# --------------------------------------------------------------------------- #
# Part C — human-authored artifact schema concreteness + union across consumers
# --------------------------------------------------------------------------- #
def test_human_artifact_schema_is_concrete_and_unioned_across_consumers():
    # ApproveRepair authors `approved_repair`; ApplyRepair reads the WHOLE object (concretely typed), Screen reads
    # `approved_repair.field` by PATH. The derived schema must union both → concrete typed fields incl. `field`.
    apply_tool = _tool("apply", {
        "repair": {"type": "object", "additionalProperties": False,
                   "properties": {"uetr": {"type": "string"},
                                  "corrections": {"type": "array", "items": {"type": "object"}},
                                  "justification": {"type": "string"}},
                   "required": ["uetr", "corrections", "justification"]}}, side_effect="side_effectful")
    screen_tool = _tool("screen", {"field": {"type": "string"}})

    proposal = CopilotProposal(elements=[
        ElementProposal(element_id="ApproveRepair",
                        executor=ExecutorProposal(type="human", role="role.payment.ops_approver"),
                        outputs=[OutputProposal(name="approved_repair", human_authored=True)]),
        ElementProposal(element_id="ApplyRepair",
                        executor=ExecutorProposal(type="capability", capability_tool="apply"),
                        input_map=[InputMapProposal(field="repair", **{"from": "artifact"}, name="approved_repair")]),
        ElementProposal(element_id="Screen",
                        executor=ExecutorProposal(type="capability", capability_tool="screen"),
                        input_map=[InputMapProposal(field="field", **{"from": "artifact"},
                                                    name="approved_repair", path="field")]),
    ])
    arts = _reconciler(proposal, [apply_tool, screen_tool])._derive_human_artifacts({})

    assert "art.payment.approved_repair" in arts
    _title, schema = arts["art.payment.approved_repair"]
    props = schema["properties"]
    # concrete typed fields from the whole-object consumer ...
    assert props["uetr"]["type"] == "string"
    assert props["corrections"]["type"] == "array"
    assert props["justification"]["type"] == "string"
    # ... UNIONED with the by-path field Screen reads
    assert props["field"]["type"] == "string"
    assert schema["required"] == sorted(["uetr", "corrections", "justification", "field"])
    assert schema["additionalProperties"] is False
    # form-renderable: real typed properties, not a bare object that forces Raw JSON
    assert props and all("type" in v for v in props.values())


def test_opaque_consumer_is_an_inherent_limit_but_well_typed_input_is_not_stripped():
    # A lone consumer that types the field as an opaque object yields a bare object (inherent limit) — but as soon
    # as ANY consumer types it concretely, those fields survive (never stripped).
    opaque = _tool("opaque_apply", {"blob": {"type": "object"}})           # no properties → opaque
    typed = _tool("typed_apply", {"blob": {"type": "object", "properties": {"note": {"type": "string"}}}})

    def _proposal(consumer_tool: str) -> CopilotProposal:
        return CopilotProposal(elements=[
            ElementProposal(element_id="Author",
                            executor=ExecutorProposal(type="human", role="role.payment.ops_analyst"),
                            outputs=[OutputProposal(name="notes", human_authored=True)]),
            ElementProposal(element_id="Consume",
                            executor=ExecutorProposal(type="capability", capability_tool=consumer_tool),
                            input_map=[InputMapProposal(field="blob", **{"from": "artifact"}, name="notes")]),
        ])

    _t, opaque_schema = _reconciler(_proposal("opaque_apply"), [opaque])._derive_human_artifacts({})["art.payment.notes"]
    assert opaque_schema["properties"] == {}                                # inherent limit — nothing to render

    _t, typed_schema = _reconciler(_proposal("typed_apply"), [typed])._derive_human_artifacts({})["art.payment.notes"]
    assert typed_schema["properties"]["note"]["type"] == "string"           # well-typed input preserved


# --------------------------------------------------------------------------- #
# ADR-054 (extended) — LLM baseline schema for human-authored artifacts
# --------------------------------------------------------------------------- #
def test_baseline_seeds_a_schema_for_a_human_artifact_no_tool_consumes():
    # Escalate authors a terminal escalation_decision no tool consumes → today it derives EMPTY. The LLM's baseline
    # `fields` seed a real form (types / enum / title), so the operator isn't faced with a blank refiner.
    proposal = CopilotProposal(elements=[
        ElementProposal(element_id="Escalate",
                        executor=ExecutorProposal(type="human", role="role.payment.supervisor"),
                        outputs=[OutputProposal(name="escalation_decision", human_authored=True, fields=[
                            OutputFieldProposal(name="decision", type="string", title="Decision", required=True,
                                                enum=["escalate", "hold", "close"]),
                            OutputFieldProposal(name="notes", type="string", title="Notes")])]),
    ])
    rec = _reconciler(proposal, [])                                # no tools → no consumers
    _title, schema = rec._derive_human_artifacts({})["art.payment.escalation_decision"]

    props = schema["properties"]
    assert props["decision"]["enum"] == ["escalate", "hold", "close"]
    assert props["decision"]["title"] == "Decision"
    assert props["notes"]["type"] == "string"
    assert schema["required"] == ["decision"]                     # required baseline field; `notes` optional
    assert schema["additionalProperties"] is False
    # provenance: seeded from the copilot, flagged for review (non-blocking)
    assert any(d.kind == "human_artifact" and "baseline" in d.summary and "escalation_decision" in d.summary
               for d in rec.decisions)


def test_tool_derived_field_stays_authoritative_and_required_baseline_extras_are_optional():
    apply_tool = _tool("apply", {"repair": {"type": "object", "properties": {"uetr": {"type": "string"}}}},
                       side_effect="side_effectful")
    proposal = CopilotProposal(elements=[
        ElementProposal(element_id="Approve",
                        executor=ExecutorProposal(type="human", role="role.payment.ops_approver"),
                        outputs=[OutputProposal(name="approved_repair", human_authored=True, fields=[
                            OutputFieldProposal(name="reviewer_notes", type="string", title="Reviewer Notes")])]),
        ElementProposal(element_id="Apply",
                        executor=ExecutorProposal(type="capability", capability_tool="apply"),
                        input_map=[InputMapProposal(field="repair", **{"from": "artifact"}, name="approved_repair")]),
    ])
    _title, schema = _reconciler(proposal, [apply_tool])._derive_human_artifacts({})["art.payment.approved_repair"]

    assert schema["properties"]["uetr"]["type"] == "string"        # tool-derived (from apply.repair.properties)
    assert schema["properties"]["reviewer_notes"]["title"] == "Reviewer Notes"   # baseline extra unioned in
    assert "uetr" in schema["required"]                            # consumed → required
    assert "reviewer_notes" not in schema["required"]              # baseline-only → optional draft


def test_baseline_does_not_override_a_tool_derived_field_on_a_name_collision():
    apply_tool = _tool("apply", {"repair": {"type": "object", "properties": {"amount": {"type": "number"}}}})
    proposal = CopilotProposal(elements=[
        ElementProposal(element_id="Approve", executor=ExecutorProposal(type="human", role="role.payment.ops_approver"),
                        outputs=[OutputProposal(name="approved_repair", human_authored=True, fields=[
                            OutputFieldProposal(name="amount", type="string", title="Amount (baseline guess)")])]),
        ElementProposal(element_id="Apply", executor=ExecutorProposal(type="capability", capability_tool="apply"),
                        input_map=[InputMapProposal(field="repair", **{"from": "artifact"}, name="approved_repair")]),
    ])
    _title, schema = _reconciler(proposal, [apply_tool])._derive_human_artifacts({})["art.payment.approved_repair"]

    assert schema["properties"]["amount"]["type"] == "number"      # tool-derived WINS, not the baseline string guess
    assert "amount" in schema["required"]


def test_opaque_tool_object_adopts_baseline_nested_properties():
    # ADR-057: the consuming tool types the human's field as an OPAQUE object (no properties). The tool type stays
    # authoritative (still `object`) but the LLM baseline's nested `properties` fill the gap — so the HITL form
    # renders real sub-fields instead of a raw JSON editor.
    apply_tool = _tool("apply", {"payload": {"type": "object"}})    # opaque — a raw editor without a baseline
    proposal = CopilotProposal(elements=[
        ElementProposal(element_id="Author", executor=ExecutorProposal(type="human", role="role.payment.ops_approver"),
                        outputs=[OutputProposal(name="approved_repair", human_authored=True, fields=[
                            OutputFieldProposal(name="repair", type="object", title="Repair", properties=[
                                OutputFieldProposal(name="field", type="string", title="Field"),
                                OutputFieldProposal(name="proposed_value", type="string", title="Proposed value")])])]),
        ElementProposal(element_id="Apply", executor=ExecutorProposal(type="capability", capability_tool="apply"),
                        input_map=[InputMapProposal(field="payload", **{"from": "artifact"}, name="approved_repair",
                                                    path="repair")]),
    ])
    _title, schema = _reconciler(proposal, [apply_tool])._derive_human_artifacts({})["art.payment.approved_repair"]

    repair = schema["properties"]["repair"]
    assert repair["type"] == "object"                              # tool type kept
    assert set(repair["properties"]) == {"field", "proposed_value"}   # baseline nested shape adopted
    assert repair["properties"]["field"]["title"] == "Field"


def test_scalar_tool_field_is_not_upgraded_to_baseline_object():
    # The mirror guard: when the tool types the field as a SCALAR, a baseline object guess must NOT override it — the
    # tool contract wins on type, the human just can't turn a string into an object.
    apply_tool = _tool("apply", {"code": {"type": "string"}})
    proposal = CopilotProposal(elements=[
        ElementProposal(element_id="Author", executor=ExecutorProposal(type="human", role="role.payment.ops_approver"),
                        outputs=[OutputProposal(name="approved_repair", human_authored=True, fields=[
                            OutputFieldProposal(name="code", type="object", title="Code", properties=[
                                OutputFieldProposal(name="nested", type="string")])])]),
        ElementProposal(element_id="Apply", executor=ExecutorProposal(type="capability", capability_tool="apply"),
                        input_map=[InputMapProposal(field="code", **{"from": "artifact"}, name="approved_repair",
                                                    path="code")]),
    ])
    _title, schema = _reconciler(proposal, [apply_tool])._derive_human_artifacts({})["art.payment.approved_repair"]

    assert schema["properties"]["code"]["type"] == "string"        # scalar kept — baseline object ignored
    assert "properties" not in schema["properties"]["code"]


# --------------------------------------------------------------------------- #
# Part 1 — an orphaned required human output is a wiring error → rewire onto the flow
# --------------------------------------------------------------------------- #
def _reconciler_with_graph(proposal: CopilotProposal, tools: list, flow_graph) -> Reconciler:
    return Reconciler(
        svc=None, domain="payment", mcp=CopilotMcpConfig(endpoint="http://wirefix-mcp:8060/mcp"),
        tools=IntrospectMcpResponse(endpoint="http://wirefix-mcp:8060/mcp", transport="streamable_http", tools=tools),
        proposal=proposal, owner="usr-owner", flow_graph=flow_graph)


def test_human_read_only_input_from_a_branch_producer_is_marked_optional():
    # Prep (guaranteed upstream) → `prepared`; Recover (SLA-branch only) → `recovery`. Serve (human) reads BOTH as
    # read-only context. The loop-back optionality that already covers capability inputs must cover human read-only
    # inputs too: `prepared` stays required, `recovery` becomes optional (absent on the normal path where the branch
    # didn't run) — so the runtime resolves Serve's inputs instead of hard-failing "not produced upstream".
    graph = FlowGraph([("Start", "Prep"), ("Prep", "Gw"), ("Gw", "Serve"),
                       ("Gw", "Recover"), ("Recover", "Serve"), ("Serve", "End")], "Start")
    serve = ElementProposal(
        element_id="Serve", executor=ExecutorProposal(type="human", role="role.payment.server"),
        read_only_inputs=[ReadOnlyInputProposal(name="prepared", source_output="prepared"),
                          ReadOnlyInputProposal(name="recovery", source_output="recovery")])
    rec = _reconciler_with_graph(CopilotProposal(elements=[serve]), [], graph)
    rec._producers = {"prepared": {"Prep"}, "recovery": {"Recover"}}
    out_artifact = {"prepared": "art.payment.prepared", "recovery": "art.payment.recovery"}
    inv = SimpleNamespace(element_id="Serve", element_kind="userTask", category="human", message_name=None)

    b = rec._binding(inv, None, out_artifact, {})

    assert b.input_sources["prepared"] == {"from": "artifact", "name": "prepared"}                    # guaranteed → required
    assert "optional" not in b.input_sources["prepared"]
    assert b.input_sources["recovery"] == {"from": "artifact", "name": "recovery", "optional": True}  # branch → optional
    assert any(d.kind == "input_map" and d.element_id == "Serve" and "recovery" in d.summary and "optional" in d.summary
               for d in rec.decisions)


def test_orphaned_human_output_is_rewired_to_the_downstream_draft_consumer():
    # DraftRepair (agent) → ApproveRepair (human approves) → ApplyRepair (side-effect). ApproveRepair reviews the
    # draft `repair_instruction` and outputs the approved `approval_repair`, but the LLM wired ApplyRepair to the
    # DRAFT — so the approval doesn't gate execution and `approval_repair` is orphaned. Reconcile rewires ApplyRepair
    # onto the approved output, and Part C can then derive its schema concretely.
    apply_tool = _tool("apply", {
        "repair": {"type": "object", "additionalProperties": False,
                   "properties": {"uetr": {"type": "string"}}, "required": ["uetr"]}}, side_effect="side_effectful")
    proposal = CopilotProposal(elements=[
        ElementProposal(element_id="DraftRepair",
                        executor=ExecutorProposal(type="capability", capability_tool="draft"),
                        output_name="repair_instruction"),
        ElementProposal(element_id="ApproveRepair",
                        executor=ExecutorProposal(type="human", role="role.payment.ops_approver"),
                        outputs=[OutputProposal(name="approval_repair", human_authored=True)],
                        read_only_inputs=[ReadOnlyInputProposal(name="draft", source_output="repair_instruction")]),
        ElementProposal(element_id="ApplyRepair",
                        executor=ExecutorProposal(type="capability", capability_tool="apply"),
                        input_map=[InputMapProposal(field="repair", **{"from": "artifact"}, name="repair_instruction")]),
    ])
    graph = FlowGraph([("DraftRepair", "ApproveRepair"), ("ApproveRepair", "ApplyRepair")], "DraftRepair")
    rec = _reconciler_with_graph(proposal, [apply_tool], graph)

    rec._rewire_orphaned_human_outputs()

    # ApplyRepair now consumes the APPROVED output, not the pre-approval draft
    assert [(m.field, m.name) for m in rec.prop_by_el["ApplyRepair"].input_map] == [("repair", "approval_repair")]
    assert any(d.decided_by == "deterministic" and d.kind == "dataflow" and d.element_id == "ApplyRepair"
               and "approved 'approval_repair'" in d.summary and "repair_instruction" in d.summary
               for d in rec.decisions)
    # and Part C now derives the human output's schema concretely (a consumer exists → real form fields)
    arts = rec._derive_human_artifacts({})
    assert "art.payment.approval_repair" in arts
    _title, schema = arts["art.payment.approval_repair"]
    assert schema["properties"]["uetr"]["type"] == "string"


def test_gate_forms_for_the_nearest_side_effect_only():
    # Draft(cap) → Approve(human, SoD-paired with Draft) → S1(side-effect) → S2(side-effect). The approval gates the
    # FIRST side-effect only; the farther one is gated transitively, not by a second consumption of the approval.
    bindable = {
        "Draft": SimpleNamespace(category="capability"), "Approve": SimpleNamespace(category="human"),
        "S1": SimpleNamespace(category="capability"), "S2": SimpleNamespace(category="capability"),
    }
    inferred = InferenceDraft(sod_candidates=[SodCandidate(elements=["Draft", "Approve"], rationale="four-eyes")])
    graph = FlowGraph([("Draft", "Approve"), ("Approve", "S1"), ("S1", "S2")], "Draft")
    side = {"S1", "S2"}

    gates = detect_approval_gates(bindable=bindable, inferred=inferred, flow_graph=graph,
                                  is_side_effect=lambda e: e in side)

    assert gates == [ApprovalGate(human="Approve", side_effect="S1", draft="Draft")]   # S1 only, never S2


def test_terminal_human_output_is_not_flagged_as_an_orphan_and_still_derives_a_schema():
    # Escalate (supervisor) authors a terminal escalation_decision — nothing consumes it and there is NO downstream
    # side-effect it could gate. It is a recorded decision, not an approval: no orphan open question, no block; its
    # schema is still registered (empty, for the operator to fill via the refiner).
    proposal = CopilotProposal(elements=[
        ElementProposal(element_id="Escalate",
                        executor=ExecutorProposal(type="human", role="role.payment.supervisor"),
                        outputs=[OutputProposal(name="escalation_decision", human_authored=True)]),
    ])
    graph = FlowGraph([("Start", "Escalate"), ("Escalate", "End")], "Start")
    rec = _reconciler_with_graph(proposal, [], graph)              # no tools → no side-effects at all

    rec._rewire_orphaned_human_outputs()

    assert not any(q.topic == "dataflow" for q in rec.questions)   # NOT flagged as an orphan
    assert any(d.decided_by == "deterministic" and "terminal recorded decision" in d.summary for d in rec.decisions)
    assert "art.payment.escalation_decision" in rec._derive_human_artifacts({})   # schema still registered


def test_ambiguous_orphan_raises_an_open_question_not_a_silent_orphan():
    # ApproveRepair reviewed TWO drafts → which one it approves is ambiguous → no rewire, a low-confidence question.
    # (The downstream consumer is side-effectful, so the unconsumed approval is a real gap — not a terminal record.)
    apply_tool = _tool("apply", {"repair": {"type": "object", "properties": {"uetr": {"type": "string"}}}},
                       side_effect="side_effectful")
    proposal = CopilotProposal(elements=[
        ElementProposal(element_id="ApproveRepair",
                        executor=ExecutorProposal(type="human", role="role.payment.ops_approver"),
                        outputs=[OutputProposal(name="approval_repair", human_authored=True)],
                        read_only_inputs=[ReadOnlyInputProposal(name="a", source_output="draft_a"),
                                          ReadOnlyInputProposal(name="b", source_output="draft_b")]),
        ElementProposal(element_id="ApplyRepair",
                        executor=ExecutorProposal(type="capability", capability_tool="apply"),
                        input_map=[InputMapProposal(field="repair", **{"from": "artifact"}, name="draft_a")]),
    ])
    graph = FlowGraph([("ApproveRepair", "ApplyRepair")], "ApproveRepair")
    rec = _reconciler_with_graph(proposal, [apply_tool], graph)

    rec._rewire_orphaned_human_outputs()

    assert [(m.field, m.name) for m in rec.prop_by_el["ApplyRepair"].input_map] == [("repair", "draft_a")]  # untouched
    assert any(q.topic == "dataflow" and q.element_id == "ApproveRepair" and "approval_repair" in q.question
               for q in rec.questions)


# --------------------------------------------------------------------------- #
# Part D — a HITL gate's role must be a human lane, never the automation/AI lane
# --------------------------------------------------------------------------- #
def _wire_inference() -> InferenceDraft:
    # Lane_Agent holds only capability tasks (automation); Lane_Approver holds the human approval task.
    return InferenceDraft(
        roles=[InferredRole(role_id="role.payment.ai_agent", label="AI Agent", source_lane="Lane_Agent"),
               InferredRole(role_id="role.payment.ops_approver", label="Ops Approver", source_lane="Lane_Approver")],
        bindings=[
            InferredBinding(element_id="Assess", element_kind="serviceTask", executor_type="capability",
                            suggested_role="role.payment.ai_agent", source_lane="Lane_Agent", suggested_hitl_mode="none"),
            InferredBinding(element_id="ApplyRepair", element_kind="serviceTask", executor_type="capability",
                            suggested_role="role.payment.ai_agent", source_lane="Lane_Agent", suggested_hitl_mode="none"),
            InferredBinding(element_id="ApproveRepair", element_kind="userTask", executor_type="human",
                            suggested_role="role.payment.ops_approver", source_lane="Lane_Approver",
                            suggested_hitl_mode="approve_actions"),
        ])


def _bare() -> Reconciler:
    return _reconciler(CopilotProposal(elements=[]), [])


def test_role_topology_detects_automation_lane_and_human_approver():
    autom, approver = _bare()._role_topology(_wire_inference(), {b.element_id: b for b in _wire_inference().bindings})
    assert autom == {"role.payment.ai_agent"}                    # lane whose members are all capability tasks
    assert approver == "role.payment.ops_approver"               # role on the human approval task


def test_side_effectful_agent_gate_gets_human_approver_not_automation_lane():
    rec = _bare()
    rec._automation_roles, rec._human_approver = rec._role_topology(_wire_inference(), {b.element_id: b for b in _wire_inference().bindings})
    inf = _wire_inference().bindings[1]                          # ApplyRepair — capability in the AI-agent lane
    mode, role = rec._clamp_hitl("ApplyRepair", None, "side_effectful", inf)

    assert mode == "approve_actions"                             # side-effect floor still enforced
    assert role == "role.payment.ops_approver"                   # HUMAN approver, not role.payment.ai_agent
    assert role not in rec._automation_roles
    assert any(d.decided_by == "deterministic" and "automation lane" in d.summary for d in rec.decisions)


def test_normal_agent_task_with_hitl_none_is_untouched():
    rec = _bare()
    rec._automation_roles, rec._human_approver = rec._role_topology(_wire_inference(), {b.element_id: b for b in _wire_inference().bindings})
    inf = _wire_inference().bindings[0]                          # Assess — plain agent step, no gate
    mode, role = rec._clamp_hitl("Assess", None, "pure", inf)
    assert mode == "none" and role is None                       # no gate → no role to humanize


def test_ambiguous_approver_leaves_the_gate_and_raises_an_open_question():
    rec = _bare()
    # automation lane present, but no human task at all → no approver can be inferred.
    inferred = InferenceDraft(
        roles=[InferredRole(role_id="role.payment.ai_agent", label="AI Agent", source_lane="Lane_Agent")],
        bindings=[InferredBinding(element_id="ApplyRepair", element_kind="serviceTask", executor_type="capability",
                                  suggested_role="role.payment.ai_agent", source_lane="Lane_Agent",
                                  suggested_hitl_mode="none")])
    rec._automation_roles, rec._human_approver = rec._role_topology(inferred, {b.element_id: b for b in inferred.bindings})
    assert rec._human_approver is None

    mode, role = rec._clamp_hitl("ApplyRepair", None, "side_effectful", inferred.bindings[0])
    assert mode == "approve_actions"                             # gate kept (control not lost)
    assert role == "role.payment.ai_agent"                       # left as-is — flagged, not silently wrong
    assert any(q.topic == "hitl" and q.element_id == "ApplyRepair" for q in rec.questions)
