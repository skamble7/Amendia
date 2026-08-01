# tests/test_copilot_loopback_optional.py
"""ADR-052 — reconcile marks loop-back / not-guaranteed from='artifact' inputs OPTIONAL (deterministic, no LLM).

A copilot-onboarded wire pack failed at runtime because ``Assess`` mapped a ``resolution`` input from
``analyst_info`` — produced by a needs-info step (``ObtainInfo``) that runs AFTER Assess and loops back. On the
first pass that artifact doesn't exist. Onboarding validation passed (the loop makes ObtainInfo topologically
reachable), but the input was marked required, so the runtime hard-failed ``input_unresolved``.

reconcile is AUTHORITATIVE here: using the BPMN flow graph + the producer map, a from='artifact' field is required
iff at least one producer of its source is a *guaranteed predecessor* of the consumer; otherwise it's optional. The
tests drive ``Reconciler._capability_input_sources`` directly with a hand-built graph (faithful to the wire loop)
so the decision is asserted deterministically, plus the chat-path round-trip of the ``optional`` flag.
"""
from __future__ import annotations

from app.models.onboarding import (
    CopilotMcpConfig,
    IntrospectedTool,
    IntrospectMcpResponse,
    ToolCompliance,
)
from app.services.copilot.flowgraph import FlowGraph
from app.services.copilot.mutations import Mutation, apply_mutations, proposal_from_session
from app.services.copilot.proposal import (
    CopilotProposal,
    ElementProposal,
    ExecutorProposal,
    InputMapProposal,
)
from app.services.copilot.reconcile import Reconciler

# Start → Prep → Assess → Gw → (needs_info) ObtainInfo → Assess ; Gw → End
# Prep is guaranteed-upstream of Assess; ObtainInfo only runs on the loop-back (after Assess).
_EDGES = [("Start", "Prep"), ("Prep", "Assess"), ("Assess", "Gw"),
          ("Gw", "ObtainInfo"), ("ObtainInfo", "Assess"), ("Gw", "End")]


def _assess_tool() -> IntrospectedTool:
    return IntrospectedTool(
        name="assess",
        description="assess repairability",
        input_schema={"type": "object", "additionalProperties": False, "properties": {
            "resolution": {"type": "object"},          # ← loop-back artifact (analyst_info)
            "exception_id": {"type": "string"},         # ← trigger
            "prep_field": {"type": "object"}}},         # ← guaranteed-upstream artifact (prep_out)
        output_schema={"type": "object", "properties": {"repairable": {"type": "boolean"}}},
        compliance=ToolCompliance(compliant=True), suggested_side_effect="pure")


def _reconciler(flow_graph):
    """A Reconciler wired with the assess tool + the Assess proposal element, ready for a direct
    ``_capability_input_sources`` call (no svc methods are touched by that path)."""
    assess = ElementProposal(
        element_id="Assess",
        executor=ExecutorProposal(type="capability", capability_tool="assess"),
        input_map=[
            InputMapProposal(field="resolution", **{"from": "artifact"}, name="analyst_info", path="outcome"),
            InputMapProposal(field="exception_id", **{"from": "trigger"}, path="exception_id"),
            InputMapProposal(field="prep_field", **{"from": "artifact"}, name="prep_out"),
        ])
    proposal = CopilotProposal(elements=[assess])
    rec = Reconciler(
        svc=None, domain="payment", mcp=CopilotMcpConfig(endpoint="http://wirefix-mcp:8060/mcp"),
        tools=IntrospectMcpResponse(endpoint="http://wirefix-mcp:8060/mcp", transport="streamable_http", tools=[_assess_tool()]),
        proposal=proposal, owner="usr-owner", flow_graph=flow_graph)
    # producer map the apply() step would have built: analyst_info ← ObtainInfo (loop-back), prep_out ← Prep.
    rec._producers = {"analyst_info": {"ObtainInfo"}, "prep_out": {"Prep"}}
    return rec, proposal.by_element()["Assess"]


def test_loopback_input_is_marked_optional_trigger_and_upstream_stay_required():
    rec, assess = _reconciler(FlowGraph(_EDGES, "Start"))
    sources = rec._capability_input_sources("Assess", "assess", assess)
    fields = sources["assess_input"]["fields"]

    # the loop-back artifact → OPTIONAL (absent-tolerant on the first pass)
    assert fields["resolution"] == {"from": "artifact", "name": "analyst_info", "path": "outcome", "optional": True}
    # a trigger-sourced field is always present → never optional
    assert fields["exception_id"] == {"from": "trigger", "path": "exception_id"}
    # a guaranteed-upstream artifact (Prep dominates Assess, no loop back to it) stays REQUIRED
    assert fields["prep_field"] == {"from": "artifact", "name": "prep_out"}
    assert "optional" not in fields["prep_field"]

    # provenance: the optional marking is recorded as a deterministic decision naming the loop-back producer
    marks = [d for d in rec.decisions if d.decided_by == "deterministic" and d.kind == "input_map"
             and "optional" in d.summary]
    assert marks and "analyst_info" in marks[0].summary and "ObtainInfo" in marks[0].summary


def test_without_a_flow_graph_the_chat_path_honors_the_proposal_flag():
    # Chat path: no diagram in hand → the reconstructed proposal's own optional flag is honored verbatim.
    rec, assess = _reconciler(flow_graph=None)
    assess.input_map[0].optional = True                    # a set_input_optional edit set this
    fields = rec._capability_input_sources("Assess", "assess", assess)["assess_input"]["fields"]
    assert fields["resolution"].get("optional") is True
    assert "optional" not in fields["prep_field"]           # not flagged → stays required on the chat path


def test_set_input_optional_mutation_toggles_and_round_trips_through_the_session():
    # The chat vocabulary: set_input_optional flips the flag; it survives a session⇄proposal round-trip so a later
    # reconcile (chat path, graph-less) keeps honoring it.
    assess = ElementProposal(
        element_id="Assess", executor=ExecutorProposal(type="capability", capability_tool="assess"),
        input_map=[InputMapProposal(field="resolution", **{"from": "artifact"}, name="analyst_info", path="outcome")])
    proposal = CopilotProposal(elements=[assess])

    applied = apply_mutations(proposal, IntrospectMcpResponse(endpoint="x", transport="streamable_http", tools=[_assess_tool()]), None,
                              [Mutation(kind="set_input_optional", element_id="Assess", input="assess_input",
                                        field="resolution", optional=True, rationale="loop-back input")])
    assert applied and "optional" in applied[0]
    assert proposal.by_element()["Assess"].input_map[0].optional is True

    # round-trip: reconstruct a proposal from a session whose stored source carries optional → the flag survives
    class _IO:
        def __init__(self, name):
            self.name = name

    class _Bind:
        element_id = "Assess"
        executor_type = "capability"
        capability_ref = "cap.payment.assess@^1.0.0"
        hitl_mode = "none"
        hitl_role = None
        outputs = [_IO("assess_output")]
        inputs = []
        input_sources = {"assess_input": {"fields": {
            "resolution": {"from": "artifact", "name": "analyst_info", "path": "outcome", "optional": True}}}}

    session = type("S", (), {"bindings": [_Bind()], "triage_rules": [],
                             "trigger_artifact": None, "copilot_report": None})()
    reconstructed = proposal_from_session(session)
    assert reconstructed.by_element()["Assess"].input_map[0].optional is True

    # toggling back off is honored too
    apply_mutations(proposal, IntrospectMcpResponse(endpoint="x", transport="streamable_http", tools=[_assess_tool()]), None,
                    [Mutation(kind="set_input_optional", element_id="Assess", field="resolution", optional=False)])
    assert proposal.by_element()["Assess"].input_map[0].optional is False
