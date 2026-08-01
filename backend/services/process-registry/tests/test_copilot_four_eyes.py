# tests/test_copilot_four_eyes.py
"""Four-eyes (human approval) structure is a SAFETY INVARIANT → deterministic, even when the LLM omits it.

A domain-neutral document-publishing pack: Prepare (agent draft) → Approve (human, different lane) → Publish
(side-effect). The fake LLM returns a HOLLOW approval — the Approve task has no outputs, no inputs, no input_map,
and Publish maps only the trigger. The engine must still reconcile into a real four-eyes gate: Approve authors an
approved artifact, Publish consumes it (not the trigger), the artifact is registered with a derived schema, and the
side-effect's approve-actions gate is assigned the HUMAN APPROVER role — never the automation/AI lane.
"""
from __future__ import annotations

import json

import pytest

from app.models.onboarding import CopilotGenerateRequest, CopilotMcpConfig
from app.services.copilot import llm as copilot_llm
from app.services.copilot.service import CopilotService
from app.services.mcp_introspect import RawMcpTool
from app.services.onboarding import OnboardingService
from tests._restaurant_copilot import FakeLLMClient
from tests.conftest import FakeMcpIntrospector, load_sample

OWNER = "usr-owner"
_NS = 'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'

# Two lanes so inference emits a four-eyes SoD pair: "Prepare …" (draft hint) in Agent, "Approve …" in Approver.
# Start → Draft(serviceTask) → Approve(userTask) → Publish(serviceTask, side-effect) → End.
_BPMN = f"""<bpmn:definitions {_NS}>
  <bpmn:process id="P" isExecutable="true">
    <bpmn:laneSet id="LS">
      <bpmn:lane id="Lane_Agent" name="Agent">
        <bpmn:flowNodeRef>Start</bpmn:flowNodeRef><bpmn:flowNodeRef>Draft</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>Publish</bpmn:flowNodeRef><bpmn:flowNodeRef>End</bpmn:flowNodeRef>
      </bpmn:lane>
      <bpmn:lane id="Lane_Approver" name="Approver">
        <bpmn:flowNodeRef>Approve</bpmn:flowNodeRef>
      </bpmn:lane>
    </bpmn:laneSet>
    <bpmn:startEvent id="Start"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="Draft" name="Prepare document"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:userTask id="Approve" name="Approve document"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:userTask>
    <bpmn:serviceTask id="Publish" name="Publish document"><bpmn:incoming>f3</bpmn:incoming><bpmn:outgoing>f4</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:endEvent id="End"><bpmn:incoming>f4</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="Start" targetRef="Draft"/>
    <bpmn:sequenceFlow id="f2" sourceRef="Draft" targetRef="Approve"/>
    <bpmn:sequenceFlow id="f3" sourceRef="Approve" targetRef="Publish"/>
    <bpmn:sequenceFlow id="f4" sourceRef="Publish" targetRef="End"/>
  </bpmn:process>
</bpmn:definitions>"""

_ACK = {"acknowledged": {"type": "boolean"}, "action_id": {"type": "string"},
        "status": {"type": "string", "enum": ["performed", "queued", "rejected"]}}


def _tools() -> list:
    return [
        RawMcpTool(name="prepare", description="Prepare a document draft",
                   input_schema={"type": "object", "additionalProperties": False, "properties": {"topic": {"type": "string"}}},
                   output_schema={"type": "object", "additionalProperties": False,
                                  "properties": {"draft": {"type": "object"}}, "required": ["draft"]}),
        RawMcpTool(name="publish", description="Publish the approved document (real-world effect)",
                   # `document` is the object the approved artifact fills; `submitter` a trigger scalar.
                   input_schema={"type": "object", "additionalProperties": False, "properties": {
                       "document": {"type": "object", "additionalProperties": False,
                                    "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
                                    "required": ["title", "body"]},
                       "submitter": {"type": "string"}}},
                   output_schema={"type": "object", "additionalProperties": False, "properties": _ACK, "required": ["acknowledged"]}),
    ]


# The HOLLOW proposal: Approve has NO outputs/inputs/input_map; Publish reads ONLY the trigger.
def _hollow_proposal() -> str:
    return json.dumps({
        "summary": "An agent prepares a document, a human approves it, then it is published.",
        "elements": [
            {"element_id": "Draft", "executor": {"type": "capability", "capability_tool": "prepare"},
             "output_name": "draft_doc", "hitl": {"mode": "none"}, "confidence": 0.9},
            {"element_id": "Approve", "executor": {"type": "human"}, "hitl": {"mode": "manual"}, "confidence": 0.9},
            {"element_id": "Publish", "executor": {"type": "capability", "capability_tool": "publish"},
             "hitl": {"mode": "none"},
             "input_map": [{"field": "submitter", "from": "trigger", "path": "submitter"}], "confidence": 0.9},
        ],
    })


@pytest.fixture
def copilot_svc(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo):
    svc = OnboardingService(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
                            FakeMcpIntrospector(_tools()), sample_envelopes=[load_sample()], profile="common_executable")
    return CopilotService(svc)


def _req():
    return CopilotGenerateRequest(
        pack_key="doc-flow", version="1.0.0", title="Document flow", domain="docflow", bpmn_xml=_BPMN,
        trigger={"submitter": "alice", "doc_type": "permit"},
        triage_rules=[{"rule_id": "any", "priority": 100, "when": {"field": "doc_type", "op": "exists"}}],
        mcp=CopilotMcpConfig(endpoint="http://docflow-mcp:8090/mcp"))


def _binding(session, eid):
    return next(b for b in session.bindings if b.element_id == eid)


async def test_hollow_approval_is_reconciled_into_a_real_four_eyes_gate(copilot_svc, monkeypatch):
    monkeypatch.setattr(copilot_llm, "_llm_client", lambda ref: FakeLLMClient([_hollow_proposal()]))
    session = await copilot_svc.generate(_req(), owner=OWNER)

    # the human task now AUTHORS an approved artifact (materialized — the LLM gave none)
    approve = _binding(session, "Approve")
    assert approve.executor_type == "human"
    authored = [o.name for o in approve.outputs]
    assert authored, "the approval task must author an approved artifact — never hollow"
    approved_name = authored[0]

    # the side-effect CONSUMES the approved artifact (not the trigger/draft)
    publish = _binding(session, "Publish")
    pub_fields = publish.input_sources.get("publish_input", {}).get("fields", {})
    doc_src = pub_fields.get("document")
    assert doc_src and doc_src.get("from") == "artifact" and doc_src.get("name") == approved_name, publish.input_sources

    # the approved artifact is REGISTERED with a schema DERIVED from publish.document (concrete, form-renderable)
    art_key = f"art.docflow.{approved_name}"
    art = next(a for a in session.authored_artifacts if a.artifact_key == art_key)
    assert set(art.json_schema["properties"]) == {"title", "body"}
    assert art.json_schema["properties"]["title"]["type"] == "string"

    # the side-effect's approve-actions gate is on the HUMAN APPROVER, never the automation/AI lane
    assert publish.hitl_mode == "approve_actions"                 # side-effect floor kept
    assert publish.hitl_role == "role.docflow.approver"
    assert publish.hitl_role != "role.docflow.agent"

    # and it assembled clean — a hollow approval could never have
    errors = [f for f in (session.dry_run_report or {}).get("findings", []) if f["severity"] == "error"]
    assert errors == [], errors


# --------------------------------------------------------------------------- #
# Part 5 — a tool bound to more than one element surfaces as an open question
# --------------------------------------------------------------------------- #
_REUSE_BPMN = f"""<bpmn:definitions {_NS}>
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="Start"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="StepA" name="Assess"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:serviceTask id="StepB" name="Notify"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:endEvent id="End"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="Start" targetRef="StepA"/>
    <bpmn:sequenceFlow id="f2" sourceRef="StepA" targetRef="StepB"/>
    <bpmn:sequenceFlow id="f3" sourceRef="StepB" targetRef="End"/>
  </bpmn:process>
</bpmn:definitions>"""


async def test_one_tool_bound_to_many_elements_raises_a_reuse_open_question(
    onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo, monkeypatch,
):
    # The MCP has only an `assess` tool; the LLM substitutes it for BOTH steps (the Notify mis-bind class). The
    # engine does NOT auto-rebind — it surfaces the reuse as an open question naming both elements.
    tools = [RawMcpTool(name="assess", description="assess",
                        input_schema={"type": "object", "additionalProperties": False, "properties": {"topic": {"type": "string"}}},
                        output_schema={"type": "object", "additionalProperties": False,
                                       "properties": {"verdict": {"type": "string"}}, "required": ["verdict"]})]
    svc = OnboardingService(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
                            FakeMcpIntrospector(tools), sample_envelopes=[load_sample()], profile="common_executable")
    proposal = json.dumps({
        "summary": "Two steps that both call the only available tool.",
        "elements": [
            {"element_id": "StepA", "executor": {"type": "capability", "capability_tool": "assess"}, "hitl": {"mode": "none"}, "confidence": 0.9},
            {"element_id": "StepB", "executor": {"type": "capability", "capability_tool": "assess"}, "hitl": {"mode": "none"}, "confidence": 0.9},
        ],
    })
    monkeypatch.setattr(copilot_llm, "_llm_client", lambda ref: FakeLLMClient([proposal]))
    session = await CopilotService(svc).generate(CopilotGenerateRequest(
        pack_key="reuse", version="1.0.0", title="Reuse", domain="reuse", bpmn_xml=_REUSE_BPMN,
        trigger={"kind": "x"}, triage_rules=[{"rule_id": "any", "priority": 100, "when": {"field": "kind", "op": "exists"}}],
        mcp=CopilotMcpConfig(endpoint="http://x/mcp")), owner=OWNER)

    qs = [q.question or "" for q in session.copilot_report.open_questions]
    assert any("assess" in q and "StepA" in q and "StepB" in q for q in qs), qs

