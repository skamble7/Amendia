"""ADR-027 Phase 1.1 — inference-oriented semantic extraction over full BPMN."""
from amendia_bpmn import extract_semantics

RICH = """<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <bpmn:collaboration id="C">
    <bpmn:participant id="P_Bank" name="Bank" processRef="P"/>
    <bpmn:participant id="P_Ext" name="Counterparty Bank"/>
    <bpmn:messageFlow id="mf1" name="pacs.008 advice" sourceRef="T_send" targetRef="P_Ext"/>
  </bpmn:collaboration>
  <bpmn:process id="P" isExecutable="false">
    <bpmn:laneSet id="LS">
      <bpmn:lane id="L_Agent" name="AI Agent Runtime">
        <bpmn:flowNodeRef>T_svc</bpmn:flowNodeRef><bpmn:flowNodeRef>Gw</bpmn:flowNodeRef>
      </bpmn:lane>
      <bpmn:lane id="L_Analyst" name="Ops Analyst">
        <bpmn:flowNodeRef>T_user</bpmn:flowNodeRef>
      </bpmn:lane>
    </bpmn:laneSet>
    <bpmn:startEvent id="St" name="received"><bpmn:messageEventDefinition id="m1"/></bpmn:startEvent>
    <bpmn:serviceTask id="T_svc" name="Assess"><bpmn:documentation>assess repairability</bpmn:documentation></bpmn:serviceTask>
    <bpmn:businessRuleTask id="T_dmn" name="Decide" calledDecision="Decision_1"/>
    <bpmn:userTask id="T_user" name="Obtain info"/>
    <bpmn:sendTask id="T_send" name="Notify bank"/>
    <bpmn:exclusiveGateway id="Gw" name="Repairable?"/>
    <bpmn:boundaryEvent id="Bnd" attachedToRef="T_user" cancelActivity="true"><bpmn:timerEventDefinition id="t1"/></bpmn:boundaryEvent>
    <bpmn:dataObject id="D1" name="dossier"/>
    <bpmn:endEvent id="En"/>
    <bpmn:sequenceFlow id="fa" name="repairable" sourceRef="Gw" targetRef="T_user">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">beneficiary.repair_verdict = "repairable"</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
  </bpmn:process>
</bpmn:definitions>"""


def test_extract_lanes_with_members():
    m = extract_semantics(RICH, "P")
    lanes = {l.id: l for l in m.lanes}
    assert lanes["L_Agent"].name == "AI Agent Runtime"
    assert set(lanes["L_Agent"].member_ids) == {"T_svc", "Gw"}
    assert lanes["L_Analyst"].member_ids == ["T_user"]
    # lane_id back-links onto the flow nodes
    assert m.node("T_svc").lane_id == "L_Agent"
    assert m.node("T_user").lane_id == "L_Analyst"


def test_extract_pools_and_message_flows():
    m = extract_semantics(RICH, "P")
    pools = {p.id: p for p in m.pools}
    assert pools["P_Bank"].is_external is False and pools["P_Bank"].process_ref == "P"
    assert pools["P_Ext"].is_external is True
    assert m.message_flows[0].name == "pacs.008 advice"
    assert m.message_flows[0].source == "T_send" and m.message_flows[0].target == "P_Ext"


def test_extract_flow_node_subtypes():
    m = extract_semantics(RICH, "P")
    by_id = {n.id: n for n in m.flow_nodes}
    assert by_id["St"].kind == "startEvent" and by_id["St"].event_subtype == "message"
    assert by_id["Bnd"].kind == "boundaryEvent" and by_id["Bnd"].event_subtype == "timer"
    assert by_id["Bnd"].attached_to == "T_user" and by_id["Bnd"].cancel_activity is True
    assert by_id["T_svc"].documentation == "assess repairability"
    assert by_id["T_dmn"].kind == "businessRuleTask" and by_id["T_dmn"].decision_ref == "Decision_1"
    assert by_id["T_send"].kind == "sendTask"


def test_extract_conditions_and_data():
    m = extract_semantics(RICH, "P")
    fa = next(f for f in m.sequence_flows if f.id == "fa")
    assert fa.condition == 'beneficiary.repair_verdict = "repairable"'
    assert [d.name for d in m.data_objects] == ["dossier"]


def test_missing_structure_is_tolerated():
    m = extract_semantics('<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
                          '<bpmn:process id="P"/></bpmn:definitions>', "P")
    assert m.process_id == "P" and m.lanes == [] and m.flow_nodes == []


def test_unparseable_xml_returns_empty_model():
    m = extract_semantics("<not xml", "P")
    assert m.flow_nodes == []
