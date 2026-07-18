"""ADR-034 / Phase 2.8 — capstone: a full-executable diagram exercising the WHOLE construct set
parses clean, pins ``common_executable``, is refused under ``common_subset``, and still classifies
documentation-only elements (lanes, external pools, message flows) as ``documented``."""
from amendia_bpmn import compilability_findings, parse, required_profile

# One diagram using: an event-based gateway (message vs timer arm), a business-rule task, an
# exclusive gateway, an embedded sub-process, a parallel fork/join, a send task, a manual task with
# an interrupting SLA timer boundary, and a service task with an error boundary. Plus documentation-
# only decoration (laneSet + an external pool + a message flow).
_CAPSTONE = """<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <bpmn:collaboration id="Collab">
    <bpmn:participant id="P_Bank" name="Bank" processRef="Cap"/>
    <bpmn:participant id="P_Core" name="Core Rails"/>
    <bpmn:messageFlow id="mf" name="advice" sourceRef="Send" targetRef="P_Core"/>
  </bpmn:collaboration>
  <bpmn:message id="Msg" name="screening_result"/>
  <bpmn:error id="Err" errorCode="PAYMENT_REJECTED"/>
  <bpmn:process id="Cap" isExecutable="true">
    <bpmn:laneSet id="LS"><bpmn:lane id="L1"><bpmn:flowNodeRef>Enrich</bpmn:flowNodeRef></bpmn:lane></bpmn:laneSet>

    <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="Enrich"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:eventBasedGateway id="EGw"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>gm</bpmn:outgoing><bpmn:outgoing>gt</bpmn:outgoing></bpmn:eventBasedGateway>
    <bpmn:intermediateCatchEvent id="MsgCatch"><bpmn:incoming>gm</bpmn:incoming><bpmn:outgoing>fm</bpmn:outgoing>
      <bpmn:messageEventDefinition messageRef="Msg"/></bpmn:intermediateCatchEvent>
    <bpmn:intermediateCatchEvent id="TimerCatch"><bpmn:incoming>gt</bpmn:incoming><bpmn:outgoing>ftc</bpmn:outgoing>
      <bpmn:timerEventDefinition><bpmn:timeDuration>PT1H</bpmn:timeDuration></bpmn:timerEventDefinition></bpmn:intermediateCatchEvent>
    <bpmn:businessRuleTask id="Assess" calledDecision="Dec"><bpmn:incoming>fm</bpmn:incoming><bpmn:incoming>ftc</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:businessRuleTask>
    <bpmn:exclusiveGateway id="XGw" default="f_alt"><bpmn:incoming>f3</bpmn:incoming><bpmn:outgoing>f_rep</bpmn:outgoing><bpmn:outgoing>f_alt</bpmn:outgoing></bpmn:exclusiveGateway>
    <bpmn:sequenceFlow id="f_rep" sourceRef="XGw" targetRef="Sub">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">beneficiary.repair_verdict = "repairable"</bpmn:conditionExpression></bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="f_alt" sourceRef="XGw" targetRef="EndAlt"/>
    <bpmn:endEvent id="EndAlt"><bpmn:incoming>f_alt</bpmn:incoming></bpmn:endEvent>

    <bpmn:subProcess id="Sub"><bpmn:incoming>f_rep</bpmn:incoming><bpmn:outgoing>f_apply</bpmn:outgoing>
      <bpmn:startEvent id="SubStart"><bpmn:outgoing>s1</bpmn:outgoing></bpmn:startEvent>
      <bpmn:parallelGateway id="Fork"><bpmn:incoming>s1</bpmn:incoming><bpmn:outgoing>pa</bpmn:outgoing><bpmn:outgoing>pb</bpmn:outgoing></bpmn:parallelGateway>
      <bpmn:sendTask id="Send"><bpmn:incoming>pa</bpmn:incoming><bpmn:outgoing>ja</bpmn:outgoing></bpmn:sendTask>
      <bpmn:manualTask id="Manual"><bpmn:incoming>pb</bpmn:incoming><bpmn:outgoing>jb</bpmn:outgoing></bpmn:manualTask>
      <bpmn:parallelGateway id="Join"><bpmn:incoming>ja</bpmn:incoming><bpmn:incoming>jb</bpmn:incoming><bpmn:outgoing>s2</bpmn:outgoing></bpmn:parallelGateway>
      <bpmn:endEvent id="SubEnd"><bpmn:incoming>s2</bpmn:incoming></bpmn:endEvent>
      <bpmn:boundaryEvent id="Sla" attachedToRef="Manual" cancelActivity="true">
        <bpmn:timerEventDefinition><bpmn:timeDuration>PT4H</bpmn:timeDuration></bpmn:timerEventDefinition></bpmn:boundaryEvent>
      <bpmn:sequenceFlow id="s1" sourceRef="SubStart" targetRef="Fork"/>
      <bpmn:sequenceFlow id="pa" sourceRef="Fork" targetRef="Send"/>
      <bpmn:sequenceFlow id="pb" sourceRef="Fork" targetRef="Manual"/>
      <bpmn:sequenceFlow id="ja" sourceRef="Send" targetRef="Join"/>
      <bpmn:sequenceFlow id="jb" sourceRef="Manual" targetRef="Join"/>
      <bpmn:sequenceFlow id="s2" sourceRef="Join" targetRef="SubEnd"/>
      <bpmn:sequenceFlow id="sla_esc" sourceRef="Sla" targetRef="EndSla"/>
    </bpmn:subProcess>

    <bpmn:serviceTask id="Apply"><bpmn:incoming>f_apply</bpmn:incoming><bpmn:outgoing>f_ok</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:endEvent id="EndOk"><bpmn:incoming>f_ok</bpmn:incoming></bpmn:endEvent>
    <bpmn:endEvent id="EndSla"><bpmn:incoming>sla_esc</bpmn:incoming></bpmn:endEvent>
    <bpmn:endEvent id="EndRej"><bpmn:incoming>rej</bpmn:incoming></bpmn:endEvent>
    <bpmn:boundaryEvent id="ErrB" attachedToRef="Apply"><bpmn:errorEventDefinition errorRef="Err"/></bpmn:boundaryEvent>

    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Enrich"/>
    <bpmn:sequenceFlow id="f2" sourceRef="Enrich" targetRef="EGw"/>
    <bpmn:sequenceFlow id="gm" sourceRef="EGw" targetRef="MsgCatch"/>
    <bpmn:sequenceFlow id="gt" sourceRef="EGw" targetRef="TimerCatch"/>
    <bpmn:sequenceFlow id="fm" sourceRef="MsgCatch" targetRef="Assess"/>
    <bpmn:sequenceFlow id="ftc" sourceRef="TimerCatch" targetRef="Assess"/>
    <bpmn:sequenceFlow id="f3" sourceRef="Assess" targetRef="XGw"/>
    <bpmn:sequenceFlow id="f_apply" sourceRef="Sub" targetRef="Apply"/>
    <bpmn:sequenceFlow id="f_ok" sourceRef="Apply" targetRef="EndOk"/>
    <bpmn:sequenceFlow id="rej" sourceRef="ErrB" targetRef="EndRej"/>
  </bpmn:process>
</bpmn:definitions>"""


def test_capstone_parses_clean_and_pins_common_executable():
    model, findings = parse(_CAPSTONE, "Cap", profile="common_executable")
    errors = [f for f in findings if f.severity == "error"]
    assert errors == [], [f.code for f in errors]
    # the whole construct set is present
    assert model.event_based_gateways and model.message_catch_events and model.timer_catch_events
    assert model.boundary_timers and model.error_boundaries and model.subprocesses
    assert model.parallel_gateways
    assert model.tasks["Assess"] == "businessRuleTask" and model.tasks["Send"] == "sendTask"
    assert model.tasks["Manual"] == "manualTask"
    # it needs — and compiles clean under — common_executable
    assert required_profile(model) == "common_executable"
    assert compilability_findings(model, profile="common_executable") == []


def test_capstone_refused_under_common_subset():
    model, _ = parse(_CAPSTONE, "Cap", profile="common_executable")
    codes = {f.code for f in compilability_findings(model, profile="common_subset")}
    # every beyond-subset construct is refused under the conservative envelope
    assert {"bpmn_parallel_gateway_unsupported", "bpmn_timer_unsupported", "bpmn_error_boundary_unsupported",
            "bpmn_message_unsupported", "bpmn_subprocess_unsupported", "bpmn_task_kind_unsupported"} <= codes


def test_capstone_documentation_only_elements_classified_documented():
    model, _ = parse(_CAPSTONE, "Cap", profile="common_executable")
    by_id = {e.id: e for e in model.elements}
    assert by_id["LS"].tier == "documented"          # lane set is documentation-only
    # external pool + message flow live in the collaboration (semantics), not the executable model —
    # the executable core never treats them as nodes.
    assert "P_Core" not in model.node_ids and "mf" not in model.node_ids
